from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.assessments.models import Option, Question, Test
from .models import Course, LearningItem, LearningTrack, Module, UserLearningItemProgress


class ProgressTests(TestCase):
    def setUp(self):
        self.track = LearningTrack.objects.create(title='Track', is_published=True)
        self.course = Course.objects.create(title='Course', learning_track=self.track, is_published=True)
        self.module = Module.objects.create(title='Module', course=self.course, is_published=True)
        self.student = User.objects.create_user(email='one@example.test', password='Password1234!', learning_track=self.track)
        self.other = User.objects.create_user(email='two@example.test', password='Password1234!', learning_track=self.track)
        self.client = APIClient()
        self.client.force_login(self.student)
        self.lecture = LearningItem.objects.create(module=self.module, type='LECTURE', title='Lecture', position=0, status='PUBLISHED')
        self.test = Test.objects.create(title='Test', is_published=True, passing_percent=70)
        self.test_item = LearningItem.objects.create(module=self.module, type='TEST', title='Test', position=1, status='PUBLISHED', test=self.test)
        self.practice = LearningItem.objects.create(module=self.module, type='PRACTICE', title='Practice', position=2, status='PUBLISHED')

    def test_lecture_progress_is_monotonic_and_isolated(self):
        url = f'/api/v1/items/{self.lecture.short_id}/progress/'
        self.assertEqual(self.client.patch(url, {'progress_percent': 67, 'user': self.other.id}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(url, {'progress_percent': 20}, format='json').data['progress_percent'], 67)
        self.assertEqual(self.client.patch(url, {'progress_percent': 101}, format='json').status_code, 400)
        self.assertFalse(UserLearningItemProgress.objects.get(user=self.student, learning_item=self.lecture).is_completed)
        other_client = APIClient()
        other_client.force_login(self.other)
        other = other_client.get(f'/api/v1/courses/{self.course.short_id}/progress/').data
        self.assertEqual(other['percent'], 0)
        self.assertEqual(other['items'], {})
        response = self.client.patch(url, {'progress_percent': 95}, format='json')
        self.assertTrue(response.data['is_completed'])
        self.assertEqual(self.client.get(f'/api/v1/courses/{self.course.short_id}/progress/').data['percent'], 32)

    def test_only_verified_attempt_can_complete_test(self):
        self.assertEqual(self.client.patch(f'/api/v1/items/{self.test_item.short_id}/progress/', {'progress_percent': 100}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/items/{self.practice.short_id}/progress/', {'progress_percent': 100}, format='json').status_code, 400)
        question = Question.objects.create(test=self.test, text='Question', position=0)
        correct = Option.objects.create(question=question, text='Yes', is_correct=True, position=0)
        wrong = Option.objects.create(question=question, text='No', is_correct=False, position=1)
        url = f'/api/v1/items/{self.test_item.short_id}/attempts/'
        failed = self.client.post(url, {'answers': [{'question': question.id, 'option': wrong.id}]}, format='json')
        self.assertEqual(failed.status_code, 201)
        self.assertFalse(failed.data['passed'])
        self.assertFalse(UserLearningItemProgress.objects.filter(user=self.student, learning_item=self.test_item).exists())
        passed = self.client.post(url, {'answers': [{'question': question.id, 'option': correct.id}]}, format='json')
        self.assertEqual(passed.status_code, 201)
        self.assertTrue(passed.data['passed'])
        state = UserLearningItemProgress.objects.get(user=self.student, learning_item=self.test_item)
        self.assertTrue(state.is_completed)
        self.assertEqual(state.progress_percent, 100)
        self.assertEqual(self.client.get(f'/api/v1/courses/{self.course.short_id}/progress/').data['percent'], 33)
