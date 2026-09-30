from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.http import Http404
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError
from common.permissions import is_admin, IsPlatformAdmin
from .models import LearningTrack, Course, Module, Lesson
from .serializers import TrackSerializer, CourseSerializer, ModuleSerializer, LessonSerializer
from .services import delete_content

def integer_query(request, name):
    value = request.query_params.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
        if parsed < 1:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise ValidationError({name: 'Ожидается положительный целочисленный ID'})

class AdminWriteMixin:
    def get_permissions(self):
        if self.request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return [IsPlatformAdmin()]
        return super().get_permissions()
    def perform_destroy(self, instance):
        delete_content(instance)

class TrackList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = TrackSerializer
    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [AllowAny()]
        return super().get_permissions()
    def get_queryset(self):
        q = LearningTrack.objects.all().order_by('id')
        if is_admin(self.request.user):
            return q
        return q.filter(is_published=True, is_active=True)

class TrackDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TrackSerializer
    lookup_field = 'short_id'
    def perform_destroy(self, instance):
        if instance.is_system:
            raise ValidationError({'detail': 'Базовую траекторию нельзя удалить'})
        super().perform_destroy(instance)
    def get_queryset(self):
        q = LearningTrack.objects.all()
        if is_admin(self.request.user):
            return q
        if self.request.user.is_authenticated:
            return q.filter(pk=self.request.user.learning_track_id, is_published=True, is_active=True)
        return q.filter(is_published=True, is_active=True)

class CourseList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = CourseSerializer
    def get_queryset(self):
        q = Course.objects.select_related('learning_track').all()
        if is_admin(self.request.user):
            track_id = integer_query(self.request, 'learning_track')
            if track_id:
                q = q.filter(learning_track_id=track_id)
            return q
        return q.filter(is_published=True, learning_track_id=self.request.user.learning_track_id,
                        learning_track__is_published=True, learning_track__is_active=True)

class CourseDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CourseSerializer
    lookup_field = 'slug'
    def get_queryset(self):
        q = Course.objects.select_related('learning_track').all()
        if is_admin(self.request.user):
            return q
        return q.filter(is_published=True, learning_track_id=self.request.user.learning_track_id,
                        learning_track__is_published=True, learning_track__is_active=True)

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        val = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        obj = queryset.filter(Q(short_id=val) | Q(slug=val)).first()
        if not obj:
            raise Http404("Курс не найден")
        self.check_object_permissions(self.request, obj)
        return obj

class ModuleList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = ModuleSerializer
    def get_queryset(self):
        q = Module.objects.select_related('course__learning_track').all()
        course_id = integer_query(self.request, 'course')
        if course_id:
            q = q.filter(course_id=course_id)
        if is_admin(self.request.user):
            return q
        return q.filter(is_published=True, course__is_published=True,
                        course__learning_track_id=self.request.user.learning_track_id,
                        course__learning_track__is_published=True, course__learning_track__is_active=True)

class ModuleDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ModuleSerializer
    lookup_field = 'short_id'
    def get_queryset(self):
        q = Module.objects.select_related('course__learning_track').all()
        if is_admin(self.request.user):
            return q
        return q.filter(is_published=True, course__is_published=True,
                        course__learning_track_id=self.request.user.learning_track_id,
                        course__learning_track__is_published=True, course__learning_track__is_active=True)

class LessonList(AdminWriteMixin, generics.ListCreateAPIView):
    serializer_class = LessonSerializer
    def get_queryset(self):
        q = Lesson.objects.select_related('module__course__learning_track').all()
        module_id = integer_query(self.request, 'module')
        if module_id:
            q = q.filter(module_id=module_id)
        if is_admin(self.request.user):
            return q
        return q.filter(status='PUBLISHED', module__is_published=True, module__course__is_published=True,
                        module__course__learning_track_id=self.request.user.learning_track_id,
                        module__course__learning_track__is_published=True, module__course__learning_track__is_active=True)

class LessonDetail(AdminWriteMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LessonSerializer
    lookup_field = 'short_id'
    def get_queryset(self):
        q = Lesson.objects.select_related('module__course__learning_track').all()
        if is_admin(self.request.user):
            return q
        return q.filter(status='PUBLISHED', module__is_published=True, module__course__is_published=True,
                        module__course__learning_track_id=self.request.user.learning_track_id,
                        module__course__learning_track__is_published=True, module__course__learning_track__is_active=True)
