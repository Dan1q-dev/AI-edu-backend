from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import User
from apps.education.models import LearningTrack

class TrackRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningTrack
        fields = ['id', 'short_id', 'title']

class UserSerializer(serializers.ModelSerializer):
    learning_track = TrackRefSerializer(read_only=True)
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'learning_track', 'date_joined']
        read_only_fields = ['id', 'email', 'role', 'date_joined']

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    learning_track = serializers.PrimaryKeyRelatedField(queryset=LearningTrack.objects.filter(is_active=True, is_published=True))
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password', 'learning_track']

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data, role='STUDENT')

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

class ProfileUpdateSerializer(serializers.ModelSerializer):
    learning_track = serializers.PrimaryKeyRelatedField(queryset=LearningTrack.objects.filter(is_active=True, is_published=True), required=False, allow_null=True)
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'learning_track']

class PasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()
