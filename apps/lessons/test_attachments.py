from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.education.models import Course, LearningTrack, Lesson, Module


class LessonAttachmentTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        track = LearningTrack.objects.create(title='Track', is_published=True, is_active=True)
        course = Course.objects.create(learning_track=track, title='Course', is_published=True)
        module = Module.objects.create(course=course, title='Module', is_published=True)
        self.lesson = Lesson.objects.create(module=module, title='Lecture')
        admin = User.objects.create_user(email='attachments-admin@example.test', password='Password1234!', role='ADMIN')
        student = User.objects.create_user(email='attachments-student@example.test', password='Password1234!', learning_track=track)
        other_track = LearningTrack.objects.create(title='Other', is_published=True, is_active=True)
        outsider = User.objects.create_user(email='attachments-other@example.test', password='Password1234!', learning_track=other_track)
        self.admin = APIClient()
        self.admin.force_login(admin)
        self.student = APIClient()
        self.student.force_login(student)
        self.outsider = APIClient()
        self.outsider.force_login(outsider)
        self.draft_url = f'/api/v1/lessons/{self.lesson.short_id}/draft/'
        self.list_url = f'/api/v1/lessons/{self.lesson.short_id}/attachments/'

    def test_files_are_available_only_after_publication_and_can_be_removed(self):
        upload = self.admin.post('/api/v1/media/files/',
                                 {'file': SimpleUploadedFile('worksheet.pdf', b'%PDF-1.4\nexample', content_type='application/pdf')},
                                 format='multipart')
        self.assertEqual(upload.status_code, 201, upload.data)
        media_id = upload.data['id']
        download_url = f'/api/v1/media/{media_id}/download/'
        self.assertEqual(self.student.get(download_url).status_code, 403)
        self.assertEqual(self.student.get(self.list_url).status_code, 403)
        draft = {'title': 'Lecture', 'description': '', 'blocks': [], 'attachments': [media_id]}
        self.assertEqual(self.admin.put(self.draft_url, draft, format='json').status_code, 200)
        self.assertEqual(self.student.get(download_url).status_code, 403)
        self.assertEqual(self.admin.get(self.draft_url).data['attachments'][0]['name'], 'worksheet.pdf')
        self.assertEqual(self.admin.post(self.draft_url).status_code, 200)
        self.assertEqual(self.student.get(self.list_url).data[0]['media'], media_id)
        download = self.student.get(download_url)
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment', download['Content-Disposition'])
        download.close()
        self.assertEqual(self.outsider.get(download_url).status_code, 403)
        self.assertEqual(self.admin.put(self.draft_url, {**draft, 'attachments': []}, format='json').status_code, 200)
        self.assertEqual(len(self.student.get(self.list_url).data), 1)
        self.assertEqual(self.admin.post(self.draft_url).status_code, 200)
        self.assertEqual(self.student.get(self.list_url).data, [])
        self.assertEqual(self.student.get(download_url).status_code, 403)

    def test_upload_rejects_unsafe_extension_and_draft_rejects_unknown_media(self):
        rejected = self.admin.post('/api/v1/media/files/',
                                   {'file': SimpleUploadedFile('script.html', b'<script>1</script>')}, format='multipart')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.student.post('/api/v1/media/files/',
                                           {'file': SimpleUploadedFile('notes.txt', b'notes')}, format='multipart').status_code, 403)
        invalid = self.admin.put(self.draft_url,
                                 {'title': 'Lecture', 'description': '', 'blocks': [], 'attachments': [999999]}, format='json')
        self.assertEqual(invalid.status_code, 400)
