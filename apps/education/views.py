from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from common.permissions import is_admin, IsPlatformAdmin
from .models import LearningTrack, Module, Lesson
from .serializers import TrackSerializer, ModuleSerializer, LessonSerializer
from .services import delete_content

class AdminWriteMixin:
    def get_permissions(self):
        if self.request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return [IsPlatformAdmin()]
        return super().get_permissions()

    def perform_destroy(self, instance):
        delete_content(instance)

class TrackList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = TrackSerializer
    def get_queryset(self):
        q = LearningTrack.objects.all().order_by('id')
        return q if is_admin(self.request.user) else q.filter(is_published=True)

class TrackDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TrackSerializer
    lookup_field = 'short_id'
    def get_queryset(self):
        q = LearningTrack.objects.all()
        return q if is_admin(self.request.user) else q.filter(is_published=True)

class ModuleList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = ModuleSerializer
    def get_queryset(self):
        q = Module.objects.select_related('track').all()
        if self.request.query_params.get('track'):
            q = q.filter(track_id=self.request.query_params['track'])
        return q if is_admin(self.request.user) else q.filter(is_published=True, track__is_published=True)
    def perform_create(self, serializer):
        if not LearningTrack.objects.filter(pk=self.request.data.get('track')).exists():
            raise ValidationError({'track': 'Траектория не найдена'})
        serializer.save()

class ModuleDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ModuleSerializer
    lookup_field = 'short_id'
    def get_queryset(self):
        q = Module.objects.all()
        return q if is_admin(self.request.user) else q.filter(is_published=True, track__is_published=True)

class LessonList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = LessonSerializer
    def get_queryset(self):
        q = Lesson.objects.select_related('module__track').all()
        if self.request.query_params.get('module'):
            q = q.filter(module_id=self.request.query_params['module'])
        return q if is_admin(self.request.user) else q.filter(status='PUBLISHED', module__is_published=True, module__track__is_published=True)

class LessonDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LessonSerializer
    queryset = Lesson.objects.select_related('module__track').all()
    lookup_field = 'short_id'
    def get_object(self):
        lesson = get_object_or_404(self.queryset, short_id=self.kwargs['short_id'])
        if not is_admin(self.request.user) and not (lesson.status == 'PUBLISHED' and lesson.module.is_published and lesson.module.track.is_published):
            raise PermissionDenied('Урок ещё не опубликован')
        self.check_object_permissions(self.request, lesson)
        return lesson
