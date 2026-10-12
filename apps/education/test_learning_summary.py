from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, UserCourseAccess
from apps.assessments.models import Test, TestAttempt
from .access import accessible_courses
from .learning import learning_dashboard
from .models import Course, LearningItem, LearningTrack, Lesson, Module, UserLearningItemProgress


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], SECURE_SSL_REDIRECT=False)
class LearningSummaryTests(TestCase):
    def setUp(self):
        self.track = LearningTrack.objects.create(title='IT', is_published=True)
        self.course = Course.objects.create(title='Course', learning_track=self.track, is_published=True)
        self.module = Module.objects.create(title='Module', course=self.course, is_published=True)
        self.items = [LearningItem.objects.create(module=self.module, type='LECTURE', title=f'Lecture {index}', position=index, status='PUBLISHED') for index in range(3)]
        self.student = User.objects.create_user('learning@example.test', 'Password123!', learning_track=self.track)
        self.client = APIClient()
        self.client.force_login(self.student)

    def dashboard(self):
        response = self.client.get('/api/v1/me/learning/')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def save_progress(self, item, percent, completed=False):
        return UserLearningItemProgress.objects.create(user=self.student, learning_item=item, progress_percent=percent, is_completed=completed)

    def test_new_course_is_available_and_starts_at_first_item(self):
        summary = self.dashboard()
        self.assertEqual(summary['active_courses'], [])
        self.assertIsNone(summary['resume_course'])
        course = summary['available_courses'][0]
        self.assertFalse(course['is_started'])
        self.assertFalse(course['is_completed'])
        self.assertEqual(course['resume_learning_item']['short_id'], self.items[0].short_id)

    def test_resume_prefers_most_recent_partial_item_and_survives_login(self):
        old = self.save_progress(self.items[0], 20)
        UserLearningItemProgress.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=1))
        self.save_progress(self.items[1], 46)
        self.client.logout()
        self.client.force_login(self.student)
        course = self.dashboard()['resume_course']
        self.assertEqual(course['resume_learning_item']['short_id'], self.items[1].short_id)
        self.assertEqual(course['percent'], 22)
        self.assertEqual(course['total_items'], 3)
        self.assertEqual(course['completed_items'], 0)

    def test_resume_moves_to_first_unfinished_item(self):
        self.save_progress(self.items[0], 95, True)
        self.assertEqual(self.dashboard()['resume_course']['resume_learning_item']['short_id'], self.items[1].short_id)

    def test_completed_course_has_100_percent_and_no_resume(self):
        for item in self.items:
            self.save_progress(item, 95, True)
        course = self.dashboard()['completed_courses'][0]
        self.assertEqual(course['percent'], 100)
        self.assertTrue(course['is_completed'])
        self.assertEqual(course['completed_items'], 3)
        self.assertIsNone(course['resume_learning_item'])
        detail = self.client.get(f'/api/v1/courses/{self.course.short_id}/progress/').data
        self.assertTrue(detail['is_completed'])
        self.assertEqual(detail['percent'], 100)

    def test_access_and_publication_are_respected(self):
        other = LearningTrack.objects.create(title='Other', is_published=True)
        Course.objects.create(title='Wrong track', learning_track=other, is_published=True)
        Course.objects.create(title='Draft', learning_track=self.track)
        denied = Course.objects.create(title='No grant', learning_track=self.track, is_published=True)
        LearningItem.objects.create(module=self.module, type='LECTURE', title='Draft item', position=3)
        self.student.course_access_mode = 'CUSTOM'
        self.student.save()
        UserCourseAccess.objects.create(user=self.student, course=self.course, is_active=True)
        UserCourseAccess.objects.create(user=self.student, course=denied, is_active=False)
        courses = self.dashboard()['available_courses']
        self.assertEqual([entry['id'] for entry in courses], [self.course.pk])
        self.assertEqual(courses[0]['total_items'], 3)

    def test_resume_never_selects_locked_module(self):
        self.course.adaptive_learning_enabled = True
        self.course.save()
        later = Module.objects.create(course=self.course, title='Later', position=1, is_published=True)
        locked_item = LearningItem.objects.create(module=later, type='LECTURE', title='Locked', status='PUBLISHED')
        self.save_progress(locked_item, 60)
        self.assertEqual(self.dashboard()['resume_course']['resume_learning_item']['short_id'], self.items[0].short_id)

    def test_failed_attempt_starts_course_without_completing_it(self):
        test = Test.objects.create(title='Final test', is_published=True)
        item = LearningItem.objects.create(module=self.module, type='TEST', title='Final test', test=test, position=3, status='PUBLISHED')
        TestAttempt.objects.create(user=self.student, test=test, test_version=1, answers=[], snapshot=[], earned_points=0, total_points=1, percent=0, passed=False)
        course = self.dashboard()['resume_course']
        self.assertTrue(course['is_started'])
        self.assertFalse(course['is_completed'])
        self.assertEqual(course['percent'], 0)
        detail = self.client.get(f'/api/v1/courses/{self.course.slug}/progress/').data
        self.assertTrue(detail['items'][item.short_id]['is_started'])

    def test_summary_query_count_does_not_grow_with_courses(self):
        for index in range(15):
            course = Course.objects.create(title=f'Course {index}', learning_track=self.track, is_published=True)
            module = Module.objects.create(course=course, title='Module', is_published=True)
            LearningItem.objects.create(module=module, type='LECTURE', title='Lecture', status='PUBLISHED')
        with self.assertNumQueries(7):
            result = learning_dashboard(self.student, accessible_courses(self.student))
        self.assertEqual(len(result['available_courses']), 16)

    def test_legacy_lesson_exposes_explicit_mapping_or_null(self):
        lesson = Lesson.objects.create(module=self.module, title='Legacy', status='PUBLISHED')
        self.assertIsNone(self.client.get(f'/api/v1/lessons/{lesson.short_id}/').data['learning_item_short_id'])
        self.items[0].lesson = lesson
        self.items[0].save()
        self.assertEqual(self.client.get(f'/api/v1/lessons/{lesson.short_id}/').data['learning_item_short_id'], self.items[0].short_id)

    def test_attempt_history_has_titles_and_pagination(self):
        test = Test.objects.create(title='Quiz', is_published=True)
        LearningItem.objects.create(module=self.module, type='TEST', title='Quiz', test=test, position=3, status='PUBLISHED')
        TestAttempt.objects.bulk_create([TestAttempt(user=self.student, test=test, test_version=1, answers=[], snapshot=[], earned_points=1, total_points=1, percent=100, passed=True) for _ in range(31)])
        response = self.client.get('/api/v1/attempts/').data
        self.assertEqual(response['count'], 31)
        self.assertIsNotNone(response['next'])
        self.assertEqual(response['results'][0]['test_title'], 'Quiz')
        self.assertEqual(response['results'][0]['course_title'], 'Course')
        self.assertEqual(len(self.client.get('/api/v1/attempts/?page=2').data['results']), 1)
