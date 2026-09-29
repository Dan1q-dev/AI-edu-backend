from io import BytesIO
from PIL import Image
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.education.models import LearningTrack, Module, Lesson
from apps.lessons.models import LessonBlock
from apps.assessments.models import Test, TestAttempt

class PlatformFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='admin@example.test', password='StrongPass321!', role='ADMIN')
        self.track = LearningTrack.objects.create(title='IT', is_published=True)
        self.student = User.objects.create_user(email='student@example.test', password='StrongPass321!', learning_track=self.track)
        from apps.education.models import Course
        self.course = Course.objects.create(learning_track=self.track, title='Python', is_published=True)
        self.module = Module.objects.create(course=self.course, title='Start', is_published=True)
        self.lesson = Lesson.objects.create(module=self.module, title='Intro', status='DRAFT')
        self.admin_client = APIClient(enforce_csrf_checks=True)
        self.admin_client.get('/api/v1/csrf/')
        self.admin_client.force_login(self.admin)
        self.student_client = APIClient(enforce_csrf_checks=True)
        self.student_client.get('/api/v1/csrf/')
        self.student_client.force_login(self.student)

    def call(self, client, method, path, data=None):
        token = client.cookies['csrftoken'].value
        return getattr(client, method)(path, data, format='json', HTTP_X_CSRFTOKEN=token)

    def test_registration_role_and_csrf(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        path = '/api/v1/auth/register/'
        payload = {'email': 'new@example.test', 'password': 'NewPass321!', 'role': 'ADMIN', 'learning_track': self.track.id}
        self.assertEqual(anonymous.post(path, payload, format='json').status_code, 403)
        anonymous.get('/api/v1/csrf/')
        response = self.call(anonymous, 'post', path, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(email='new@example.test').role, 'STUDENT')
        self.assertEqual(User.objects.get(email='new@example.test').learning_track, self.track)
        missing_track = {'email': 'missing@example.test', 'password': 'NewPass321!'}
        self.assertEqual(self.call(anonymous, 'post', path, missing_track).status_code, 400)
        inactive = LearningTrack.objects.create(title='Closed', is_published=True, is_active=False)
        closed_payload = {'email': 'closed@example.test', 'password': 'NewPass321!', 'learning_track': inactive.id}
        self.assertEqual(self.call(anonymous, 'post', path, closed_payload).status_code, 400)

    def test_course_hierarchy_and_track_isolation(self):
        from apps.education.models import Course
        other_track = LearningTrack.objects.create(title='Other', is_published=True)
        other_course = Course.objects.create(learning_track=other_track, title='Other course', is_published=True)
        other_module = Module.objects.create(course=other_course, title='Other module', is_published=True)
        other_lesson = Lesson.objects.create(module=other_module, title='Other lesson', status='PUBLISHED')
        self.lesson.status = 'PUBLISHED'
        self.lesson.save()
        self.assertEqual(self.student_client.get('/api/v1/courses/').json()['results'][0]['title'], 'Python')
        self.assertEqual(self.student_client.get(f'/api/v1/courses/{other_course.slug}/').status_code, 404)
        self.assertEqual(self.student_client.get(f'/api/v1/lessons/{other_lesson.short_id}/').status_code, 404)
        self.assertEqual(self.student_client.get(f'/api/v1/modules/?course={other_course.id}').json()['results'], [])
        self.assertEqual(self.student_client.get('/api/v1/modules/?course=invalid').status_code, 400)

    def test_login_profile_password_and_logout(self):
        client = APIClient(enforce_csrf_checks=True)
        path = '/api/v1/auth/login/'
        credentials = {'email': 'student@example.test', 'password': 'StrongPass321!'}
        self.assertEqual(client.post(path, credentials, format='json').status_code, 403)
        client.get('/api/v1/csrf/')
        self.assertEqual(self.call(client, 'post', path, credentials).status_code, 200)
        self.assertEqual(client.get('/api/v1/auth/me/').status_code, 200)
        self.assertEqual(self.call(client, 'patch', '/api/v1/auth/me/', {'first_name': 'Learner'}).json()['first_name'], 'Learner')
        self.assertEqual(self.call(client, 'post', '/api/v1/auth/password/', {'current_password': 'StrongPass321!', 'new_password': 'NewStrongPass456!'}).status_code, 204)
        self.assertEqual(self.call(client, 'post', '/api/v1/auth/logout/').status_code, 204)
        self.assertEqual(client.get('/api/v1/auth/me/').status_code, 403)
        self.assertEqual(self.call(client, 'post', path, {'email': 'student@example.test', 'password': 'NewStrongPass456!'}).status_code, 200)

    def test_draft_access_and_atomic_block_validation(self):
        path = f'/api/v1/lessons/{self.lesson.short_id}/blocks/'
        self.assertEqual(self.student_client.get(f'/api/v1/lessons/{self.lesson.short_id}/').status_code, 404)
        self.assertEqual(self.student_client.get(path).status_code, 403)
        good = [{'type': 'TEXT', 'position': 0, 'content': '# Hello', 'media': None, 'config': {}},
                {'type': 'TEXT', 'position': 1, 'content': 'World', 'media': None, 'config': {}}]
        self.assertEqual(self.call(self.admin_client, 'put', path, good).status_code, 200)
        reordered = [{**good[1], 'position': 0}, {**good[0], 'position': 1}]
        self.assertEqual(self.call(self.admin_client, 'put', path, reordered).status_code, 200)
        self.assertEqual(list(self.lesson.blocks.values_list('content', flat=True)), ['World', '# Hello'])
        bad = good + [{'type': 'TEXT', 'position': 3, 'content': 'bad', 'media': None, 'config': {}}]
        self.assertEqual(self.call(self.admin_client, 'put', path, bad).status_code, 400)
        self.assertEqual(self.lesson.blocks.count(), 2)
        self.assertEqual(self.call(self.student_client, 'put', path, good).status_code, 403)
        self.call(self.admin_client, 'patch', f'/api/v1/lessons/{self.lesson.short_id}/', {'status': 'PUBLISHED'})
        self.assertEqual(self.student_client.get(path).status_code, 200)

    def test_editor_draft_does_not_change_published_lesson_until_publish(self):
        self.lesson.status = 'PUBLISHED'
        self.lesson.save()
        LessonBlock.objects.create(lesson=self.lesson, type='TEXT', position=0, content='Published version')
        path = f'/api/v1/lessons/{self.lesson.short_id}/draft/'
        update = {
            'title': 'Draft title', 'description': 'Draft summary',
            'blocks': [{'type': 'TEXT', 'position': 0,
                        'content': '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Draft version"}]}]}',
                        'media': None, 'config': {}}],
        }
        self.assertEqual(self.call(self.admin_client, 'put', path, update).status_code, 200)
        self.assertEqual(self.student_client.get(f'/api/v1/lessons/{self.lesson.short_id}/').json()['title'], 'Intro')
        public = self.student_client.get(f'/api/v1/lessons/{self.lesson.short_id}/blocks/').json()
        self.assertEqual(public[0]['content'], 'Published version')
        self.assertEqual(self.call(self.admin_client, 'post', path).status_code, 200)
        self.assertEqual(self.student_client.get(f'/api/v1/lessons/{self.lesson.short_id}/').json()['title'], 'Draft title')
        public = self.student_client.get(f'/api/v1/lessons/{self.lesson.short_id}/blocks/').json()
        self.assertIn('Draft version', public[0]['content'])

    def test_test_secrecy_limits_and_versioned_results(self):
        self.lesson.status = 'PUBLISHED'; self.lesson.save()
        path = f'/api/v1/lessons/{self.lesson.short_id}/test/'
        payload = {'title': 'Quiz', 'passing_percent': 70, 'max_attempts': 1, 'is_published': True,
            'questions': [{'text': 'Two plus two?', 'position': 0, 'points': 2, 'options': [
                {'text': 'Four', 'position': 0, 'is_correct': True}, {'text': 'Five', 'position': 1, 'is_correct': False}]}]}
        self.assertEqual(self.call(self.admin_client, 'put', path, payload).status_code, 200)
        student_test = self.student_client.get(path).json()
        self.assertNotIn('is_correct', str(student_test))
        questions_response = self.student_client.get(f"/api/v1/tests/{student_test['id']}/questions/")
        self.assertEqual(questions_response.status_code, 200)
        self.assertNotIn('is_correct', str(questions_response.json()))
        question = student_test['questions'][0]
        answer = [{'question': question['id'], 'option': question['options'][0]['id']}]
        attempt_path = f'/api/v1/lessons/{self.lesson.short_id}/attempts/'
        result = self.call(self.student_client, 'post', attempt_path, {'answers': answer})
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.json()['passed'])
        self.assertEqual(self.call(self.student_client, 'post', attempt_path, {'answers': answer}).status_code, 400)
        payload['questions'][0]['options'][0]['text'] = 'Changed answer'
        self.call(self.admin_client, 'put', path, payload)
        attempt = TestAttempt.objects.get()
        self.assertEqual(attempt.test_version, 1)
        self.assertEqual(attempt.snapshot[0]['correct'], 'Four')
        self.assertEqual(self.call(self.admin_client, 'delete', f'/api/v1/lessons/{self.lesson.short_id}/').status_code, 400)
        self.assertTrue(Lesson.objects.filter(pk=self.lesson.pk).exists())

    def test_image_upload_validation(self):
        path = '/api/v1/media/'
        self.assertEqual(self.student_client.post(path, {'file': 'bad'}, HTTP_X_CSRFTOKEN=self.student_client.cookies['csrftoken'].value).status_code, 403)
        from django.core.files.uploadedfile import SimpleUploadedFile
        invalid = SimpleUploadedFile('bad.png', b'not an image', content_type='image/png')
        self.assertEqual(self.admin_client.post(path, {'file': invalid}, HTTP_X_CSRFTOKEN=self.admin_client.cookies['csrftoken'].value).status_code, 400)
        image = Image.new('RGB', (10, 10), 'red')
        out = BytesIO(); image.save(out, format='PNG')
        file = SimpleUploadedFile('photo.png', out.getvalue(), content_type='image/png')
        token = self.admin_client.cookies['csrftoken'].value
        import tempfile
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            response = self.admin_client.post(path, {'file': file}, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.student_client.get(response.json()['url']).status_code, 403)
