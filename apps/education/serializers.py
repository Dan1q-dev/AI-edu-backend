from rest_framework import serializers
from .models import LearningTrack, Module, Lesson

class TrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningTrack
        fields = ['id', 'title', 'slug', 'description', 'cover', 'is_published', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['id', 'track', 'title', 'description', 'position', 'is_published']
        read_only_fields = ['id']

class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'module', 'title', 'description', 'position', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
