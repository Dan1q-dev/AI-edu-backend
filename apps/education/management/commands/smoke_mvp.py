import json
import secrets
from io import BytesIO
from uuid import uuid4
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.test import Client
from apps.accounts.models import User
from apps.education.models import LearningTrack, Course, Module, Lesson
from apps.lessons.models import LessonBlock
from apps.assessments.models import Test, TestAttempt
from apps.mediafiles.models import MediaFile

class Command(BaseCommand):
    help = 'Exercise the MVP through real API views, database and configured object storage'

    def handle(self, *args, **options):
        marker = uuid4().hex[:10]
        admin = User.objects.create_user(email=f'admin-{marker}@example.test', password=secrets.token_urlsafe(20), role='ADMIN')
        admin_client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost')
        student_client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost')
        track = course = module = lesson = media = student = None

        def send(client, method, path, data):
            token = client.cookies['csrftoken'].value
            return getattr(client, method)(path, data=json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN=token)

        try:
            admin_client.get('/api/v1/csrf/')
            admin_client.force_login(admin)
            response = send(admin_client, 'post', '/api/v1/tracks/', {'title': 'Smoke track', 'is_published': True})
            assert response.status_code == 201, response.content
            track = LearningTrack.objects.get(pk=response.json()['id'])
            response = send(admin_client, 'post', '/api/v1/courses/', {'learning_track': track.id, 'title': 'Smoke course', 'is_published': True})
            assert response.status_code == 201, response.content
            course = Course.objects.get(pk=response.json()['id'])
            response = send(admin_client, 'post', '/api/v1/modules/', {'course': course.id, 'title': 'Module', 'position': 0, 'is_published': True})
            assert response.status_code == 201, response.content
            module = Module.objects.get(pk=response.json()['id'])
            response = send(admin_client, 'post', '/api/v1/lessons/', {'module': module.id, 'title': 'Lesson', 'position': 0})
            assert response.status_code == 201, response.content
            lesson = Lesson.objects.get(pk=response.json()['id'])
            lesson_url_id = response.json()['short_id']
            student_client.get('/api/v1/csrf/')
            response = send(student_client, 'post', '/api/v1/auth/register/', {'email': f'student-{marker}@example.test', 'password': secrets.token_urlsafe(20), 'learning_track': track.id})
            assert response.status_code == 201, response.content
            student = User.objects.get(pk=response.json()['id'])
            assert student_client.get(f'/api/v1/lessons/{lesson_url_id}/').status_code == 404
            image = Image.new('RGB', (12, 12), 'blue')
            out = BytesIO(); image.save(out, format='PNG')
            upload = SimpleUploadedFile('diagram.png', out.getvalue(), content_type='image/png')
            response = admin_client.post('/api/v1/media/', {'file': upload}, HTTP_X_CSRFTOKEN=admin_client.cookies['csrftoken'].value)
            assert response.status_code == 201, response.content
            media = MediaFile.objects.get(pk=response.json()['id'])
            blocks = [{'type': 'TEXT', 'position': 0, 'content': '# Introduction', 'media': None, 'config': {}},
                      {'type': 'IMAGE', 'position': 1, 'content': 'Diagram', 'media': media.id, 'config': {}},
                      {'type': 'TEXT', 'position': 2, 'content': 'Conclusion', 'media': None, 'config': {}}]
            response = send(admin_client, 'put', f'/api/v1/lessons/{lesson_url_id}/blocks/', blocks)
            assert response.status_code == 200, response.content
            payload = {'title': 'Quiz', 'passing_percent': 70, 'max_attempts': 1, 'is_published': True,
                'questions': [{'text': 'Correct?', 'position': 0, 'points': 1, 'options': [
                    {'text': 'Yes', 'position': 0, 'is_correct': True}, {'text': 'No', 'position': 1, 'is_correct': False}]}]}
            response = send(admin_client, 'put', f'/api/v1/lessons/{lesson_url_id}/test/', payload)
            assert response.status_code == 200, response.content
            response = send(admin_client, 'patch', f'/api/v1/lessons/{lesson_url_id}/', {'status': 'PUBLISHED'})
            assert response.status_code == 200, response.content
            assert student_client.get(f'/api/v1/lessons/{lesson_url_id}/').status_code == 200
            assert student_client.get(f'/api/v1/media/{media.id}/').status_code == 200
            test = student_client.get(f'/api/v1/lessons/{lesson_url_id}/test/').json()
            assert 'is_correct' not in str(test)
            q = test['questions'][0]
            response = send(student_client, 'post', f'/api/v1/lessons/{lesson_url_id}/attempts/', {'answers': [{'question': q['id'], 'option': q['options'][0]['id']}]})
            assert response.status_code == 201 and response.json()['passed'], response.content
            assert TestAttempt.objects.filter(test__lesson=lesson, user=student).count() == 1
            self.stdout.write(self.style.SUCCESS('MVP smoke: auth, PostgreSQL, lesson, MinIO image, test and attempt OK'))
        finally:
            if lesson:
                TestAttempt.objects.filter(test__lesson=lesson).delete()
                Test.objects.filter(lesson=lesson).delete()
                LessonBlock.objects.filter(lesson=lesson).delete()
                lesson.delete()
            if module: module.delete()
            if course: course.delete()
            if track: track.delete()
            if media:
                media.file.delete(save=False)
                media.delete()
            if student: student.delete()
            admin.delete()
