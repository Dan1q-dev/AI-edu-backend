from rest_framework import serializers
from .models import LearningTrack, Course, Module, Lesson

class TrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningTrack
        fields = ['id', 'short_id', 'title', 'description', 'cover', 'is_published', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'short_id', 'created_at', 'updated_at']

class CourseSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True, allow_unicode=True)
    class Meta:
        model = Course
        fields = ['id', 'short_id', 'learning_track', 'title', 'slug', 'description', 'cover', 'position', 'is_published', 'created_at', 'updated_at']
        read_only_fields = ['id', 'short_id', 'created_at', 'updated_at']
    def validate(self, attrs):
        track = attrs.get('learning_track', getattr(self.instance, 'learning_track', None))
        if track is None:
            raise serializers.ValidationError({'learning_track': 'Выберите направление обучения'})
        slug = attrs.get('slug')
        if slug:
            matches = Course.objects.filter(slug=slug)
            if self.instance:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                raise serializers.ValidationError({'slug': 'Такой адрес курса уже используется'})
        return attrs

class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['id', 'short_id', 'course', 'title', 'description', 'position', 'is_published']
        read_only_fields = ['id', 'short_id']

class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'short_id', 'module', 'title', 'description', 'position', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'short_id', 'created_at', 'updated_at']
