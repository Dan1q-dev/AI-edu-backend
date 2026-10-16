import tempfile

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User, UserCourseAccess
from apps.activities.models import PracticeDefinition, PracticeResult, PracticeVersion
from apps.activities.services import start_submission, submit
from apps.activities.testing import configure_checklist
from apps.assessments.models import Option, Question, Test, TestAttempt
from apps.lessons.models import LessonAttachment, LessonBlock
from apps.mediafiles.models import MediaFile
from .models import (Course, LearningItem, LearningTrack, Lesson, Module,
                     PracticeSubmission, UserLearningItemProgress)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SoftDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.track = LearningTrack.objects.create(title='Track', is_published=True)
        cls.course = Course.objects.create(title='Course', learning_track=cls.track, is_published=True)
        cls.module = Module.objects.create(title='Module', course=cls.course, is_published=True)
        cls.admin = User.objects.create_user('admin@example.test', 'Password123!', role='ADMIN')
        cls.student = User.objects.create_user('student@example.test', 'Password123!', learning_track=cls.track)
        cls.lesson = Lesson.objects.create(title='Lecture', module=cls.module, status='PUBLISHED')
        cls.lecture = LearningItem.objects.create(title='Lecture', module=cls.module, type='LECTURE',
            lesson=cls.lesson, status='PUBLISHED', position=0)
        cls.practice = LearningItem.objects.create(title='Practice', module=cls.module, type='PRACTICE', position=1)
        configure_checklist(cls.practice, ['Done'], cls.admin)
        cls.practice.refresh_from_db()
        cls.test = Test.objects.create(title='Test', is_published=True)
        cls.test_item = LearningItem.objects.create(title='Test', module=cls.module, type='TEST',
            test=cls.test, status='PUBLISHED', position=2)
        cls.question = Question.objects.create(test=cls.test, text='Question', position=0)
        cls.option = Option.objects.create(question=cls.question, text='Answer', is_correct=True, position=0)
        cls.attempt = TestAttempt.objects.create(user=cls.student, test=cls.test, test_version=1,
            answers=[{'question': cls.question.pk, 'option': cls.option.pk}], snapshot=[{'answer': 'Answer'}],
            earned_points=1, total_points=1, percent=100, passed=True)
        cls.progress = UserLearningItemProgress.objects.create(user=cls.student, learning_item=cls.lecture,
            progress_percent=100, is_completed=True)
        cls.submission = start_submission(cls.student, cls.practice)
        submit(cls.student, cls.practice, cls.submission.pk, {'checks': [True]})
        cls.grant = UserCourseAccess.objects.create(user=cls.student, course=cls.course)
        cls.block = LessonBlock.objects.create(lesson=cls.lesson, type='TEXT', position=0, content='Saved text')

    def setUp(self):
        self.admin_client, self.client = APIClient(), APIClient()
        self.admin_client.force_login(self.admin)
        self.client.force_login(self.student)

    def assert_archived(self, *objects):
        for obj in objects:
            self.assertFalse(type(obj).objects.filter(pk=obj.pk).exists())
            self.assertIsNotNone(type(obj).all_objects.get(pk=obj.pk).deleted_at)

    def assert_history(self):
        attempt = TestAttempt.objects.select_related('user', 'test').get(pk=self.attempt.pk)
        self.assertEqual(attempt.snapshot, [{'answer': 'Answer'}])
        self.assertEqual(attempt.user.email, self.student.email)
        self.assertEqual(attempt.test.title, self.test.title)
        self.assertEqual(Question.objects.get(pk=self.question.pk).text, 'Question')
        self.assertTrue(Option.objects.filter(pk=self.option.pk).exists())
        self.assertEqual(UserLearningItemProgress.objects.get(pk=self.progress.pk).learning_item.title, 'Lecture')
        submission = PracticeSubmission.objects.select_related('item', 'practice_version__practice_definition').get(pk=self.submission.pk)
        self.assertEqual(submission.criteria_snapshot[0]['title'], 'Done')
        self.assertEqual(submission.practice_version.practice_definition.title, 'Practice')
        self.assertEqual(PracticeResult.objects.get(submission=submission).psi_value, 1)
        self.assertEqual(LessonBlock.objects.get(pk=self.block.pk).content, 'Saved text')

    def test_course_delete_hides_tree_but_keeps_all_content_and_history(self):
        unrelated = Course.objects.create(title='Unrelated', learning_track=self.track, is_published=True)
        response = self.admin_client.delete(f'/api/v1/courses/{self.course.slug}/')
        self.assertEqual(response.status_code, 204)
        self.assert_archived(self.course, self.module, self.lesson, self.lecture, self.practice, self.test_item,
                             self.test, self.practice.practice)
        self.assert_history()
        self.assertTrue(Course.objects.filter(pk=unrelated.pk).exists())
        self.assertTrue(UserCourseAccess.objects.filter(pk=self.grant.pk).exists())
        self.assertTrue(PracticeVersion.objects.filter(pk=self.submission.practice_version_id).exists())
        for client in (self.client, self.admin_client):
            for path in ('modules/', 'lessons/', 'items/'):
                self.assertEqual(client.get('/api/v1/' + path).data['count'], 0)
            for path in (f'courses/{self.course.slug}/', f'modules/{self.module.short_id}/',
                         f'lessons/{self.lesson.short_id}/', f'items/{self.practice.short_id}/practice/',
                         f'items/{self.test_item.short_id}/test/', f'items/{self.test_item.short_id}/attempts/',
                         f'tests/{self.test.pk}/questions/'):
                self.assertEqual(client.get('/api/v1/' + path).status_code, 404, path)
        self.assertEqual(self.client.get(f'/api/v1/courses/{self.course.slug}/progress/').status_code, 404)
        dashboard = self.client.get('/api/v1/me/learning/').data
        self.assertEqual([row['id'] for row in dashboard['available_courses']], [unrelated.pk])
        self.assertIsNone(dashboard['resume_course'])
        # The history endpoint remains usable, including archived test titles.
        history = self.client.get('/api/v1/attempts/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data['results'][0]['test_title'], 'Test')
        detail = self.admin_client.get(f'/api/v1/admin/users/{self.student.pk}/').data
        self.assertEqual(detail['accessible_course_count'], 1)
        self.assertEqual(detail['course_ids'], [])

    def test_practice_delete_retains_published_version_and_results_and_frees_position(self):
        self.assertEqual(self.admin_client.delete(f'/api/v1/items/{self.practice.short_id}/').status_code, 204)
        self.assert_archived(self.practice, self.practice.practice)
        self.assert_history()
        for suffix in ('', 'history/', 'draft/'):
            self.assertEqual(self.admin_client.get(f'/api/v1/items/{self.practice.short_id}/practice/{suffix}').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/items/{self.practice.short_id}/practice/start/').status_code, 404)
        new = self.admin_client.post('/api/v1/items/', {'title': 'New practice', 'type': 'PRACTICE', 'module': self.module.pk}, format='json')
        self.assertEqual(new.status_code, 201, new.data)
        self.assertEqual(list(self.module.items.values_list('type', 'position')), [('LECTURE', 0), ('PRACTICE', 1), ('TEST', 2)])

    def test_test_delete_keeps_answers_and_allows_replacement(self):
        self.assertEqual(self.admin_client.delete(f'/api/v1/items/{self.test_item.short_id}/').status_code, 204)
        self.assert_archived(self.test_item, self.test)
        self.assert_history()
        response = self.admin_client.post('/api/v1/items/', {'title': 'New test', 'type': 'TEST', 'module': self.module.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data['test'], self.test.pk)
        self.assertEqual(response.data['position'], 2)

    def test_legacy_lesson_delete_archives_its_item_and_legacy_assessments(self):
        legacy_test = Test.objects.create(title='Legacy test', lesson=self.lesson)
        legacy_practice = PracticeDefinition.objects.create(title='Legacy practice', lesson=self.lesson)
        self.assertEqual(self.admin_client.delete(f'/api/v1/lessons/{self.lesson.short_id}/').status_code, 204)
        self.assert_archived(self.lesson, self.lecture, legacy_test, legacy_practice)
        self.assertTrue(LearningItem.objects.filter(pk=self.test_item.pk).exists())
        self.assert_history()
        self.assertEqual(list(self.module.items.values_list('position', flat=True)), [0, 1])

    def test_lecture_delete_preserves_independent_legacy_test_item(self):
        self.test.lesson = self.lesson
        self.test.save()
        self.assertEqual(self.admin_client.delete(f'/api/v1/items/{self.lecture.short_id}/').status_code, 204)
        self.assertTrue(Test.objects.filter(pk=self.test.pk).exists())
        self.assertEqual(self.client.get(f'/api/v1/items/{self.test_item.short_id}/test/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/v1/lessons/{self.lesson.short_id}/attempts/').status_code, 404)

    def test_queryset_delete_cascades_and_system_track_validation_is_atomic(self):
        system = LearningTrack.objects.filter(is_system=True).first()
        self.assertIsNotNone(system)
        with self.assertRaises(ValidationError):
            LearningTrack.objects.filter(pk__in=[system.pk, self.track.pk]).delete()
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        count, counts = Course.objects.filter(pk=self.course.pk).delete()
        self.assertGreater(count, 1)
        self.assertEqual(counts['education.Course'], 1)
        self.assert_archived(self.course, self.module, self.test)
        self.assert_history()

    def test_track_delete_hides_courses_and_keeps_user_and_grants(self):
        self.assertEqual(self.admin_client.delete(f'/api/v1/tracks/{self.track.short_id}/').status_code, 204)
        self.assert_archived(self.track, self.course, self.module, self.lesson)
        self.assert_history()
        self.assertEqual(User.objects.get(pk=self.student.pk).learning_track_id, self.track.pk)
        self.assertTrue(UserCourseAccess.objects.filter(pk=self.grant.pk).exists())
        self.assertEqual(self.client.get('/api/v1/courses/').data['count'], 0)
        self.assertEqual(self.admin_client.get(f'/api/v1/admin/users/{self.student.pk}/').data['accessible_course_count'], 0)

    def test_user_delete_blocks_login_and_sessions_and_keeps_history(self):
        url = f'/api/v1/admin/users/{self.student.pk}/'
        self.assertEqual(self.admin_client.delete(url).status_code, 204)
        self.assert_archived(self.student)
        self.assertFalse(User.all_objects.get(pk=self.student.pk).is_active)
        self.assertIsNone(authenticate(email=self.student.email, password='Password123!'))
        self.assertEqual(self.client.get('/api/v1/auth/me/').status_code, 403)
        self.assertEqual(self.admin_client.get(url).status_code, 404)
        self.assertEqual(self.admin_client.patch(url, {'is_active': True}, format='json').status_code, 404)
        self.assertEqual(self.admin_client.delete(url).status_code, 404)
        self.assertEqual(self.admin_client.get('/api/v1/admin/users/?search=student').data['count'], 0)
        self.assert_history()

    def test_deleted_email_and_slug_remain_reserved_without_server_errors(self):
        self.student.delete()
        payload = {'email': self.student.email, 'password': 'GoodStrongPassword42!', 'learning_track': self.track.pk}
        self.assertEqual(APIClient().post('/api/v1/auth/register/', payload, format='json').status_code, 400)
        self.assertEqual(self.admin_client.post('/api/v1/admin/users/', payload, format='json').status_code, 400)
        self.course.delete()
        response = self.admin_client.post('/api/v1/courses/', {'title': 'Course', 'learning_track': self.track.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data['slug'], self.course.slug)
        response = self.admin_client.post('/api/v1/courses/', {'title': 'Course', 'learning_track': self.track.pk, 'slug': self.course.slug}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_student_and_anonymous_cannot_delete_users_or_content(self):
        for client in (self.client, APIClient()):
            for path in (f'admin/users/{self.admin.pk}/', f'courses/{self.course.slug}/', f'items/{self.practice.short_id}/'):
                self.assertEqual(client.delete('/api/v1/' + path).status_code, 403)

    def test_media_delete_keeps_file_and_archived_draft_prevents_cleanup(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            media = MediaFile.objects.create(file=SimpleUploadedFile('saved.txt', b'Saved attachment'),
                original_name='saved.txt', content_type='text/plain', size=16, uploaded_by=self.admin)
            self.assertEqual(self.admin_client.delete(f'/api/v1/media/{media.pk}/').status_code, 204)
            self.assert_archived(media)
            self.assertTrue(media.file.storage.exists(media.file.name))
            self.assertEqual(self.admin_client.get(f'/api/v1/media/{media.pk}/').status_code, 404)
            draft_media = MediaFile.objects.create(file=SimpleUploadedFile('draft.txt', b'Draft attachment'),
                original_name='draft.txt', content_type='text/plain', size=16, uploaded_by=self.admin)
            self.lesson.draft_data = {'blocks': [], 'attachments': [{'media': draft_media.pk}]}
            self.lesson.save()
            attachment = LessonAttachment.objects.create(lesson=self.lesson, media=draft_media, position=0)
            self.lesson.delete()
            self.assertEqual(LessonAttachment.objects.get(pk=attachment.pk).media_id, draft_media.pk)
            call_command('cleanup_unused_media', delete=True, verbosity=0)
            self.assertTrue(MediaFile.objects.filter(pk=draft_media.pk).exists())
            self.assertTrue(draft_media.file.storage.exists(draft_media.file.name))
            self.assertEqual(self.client.get(f'/api/v1/media/{draft_media.pk}/download/').status_code, 403)
