from rest_framework import serializers
from .models import PracticeVersion, PracticeResult


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Ожидается объект')
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: 'Неизвестное поле' for key in unknown})
        return super().to_internal_value(data)


class DraftInput(StrictSerializer):
    practice_type = serializers.CharField(max_length=100)
    plugin_version = serializers.CharField(max_length=30, default='1.0.0')
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default='')
    config = serializers.JSONField()


class SubmissionInput(StrictSerializer):
    submission_id = serializers.IntegerField(min_value=1)
    submission_data = serializers.JSONField()


class VersionOutput(serializers.ModelSerializer):
    practice_type = serializers.CharField(source='practice_definition.practice_type')
    class Meta:
        model = PracticeVersion
        fields = ['id', 'practice_definition', 'practice_type', 'plugin_version', 'version_number',
                  'title', 'description', 'config', 'status', 'created_at', 'published_at']


class ResultOutput(serializers.ModelSerializer):
    class Meta:
        model = PracticeResult
        fields = ['self_assessment_score', 'automatic_score', 'teacher_score', 'effective_score',
                  'grading_source', 'psi_value', 'psi_source']


class ManifestOutput(serializers.Serializer):
    type = serializers.CharField()
    version = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    grading = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    available = serializers.BooleanField()
    config_schema = serializers.JSONField()
    frontend_editor = serializers.CharField()
    student_runtime = serializers.CharField()


class DraftOutput(serializers.Serializer):
    draft = VersionOutput(allow_null=True)
    published = VersionOutput(allow_null=True)
    versions = VersionOutput(many=True)


class SubmissionOutput(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    practice_version = serializers.IntegerField()
    submission_data = serializers.JSONField()
    criteria_snapshot = serializers.JSONField()
    started_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class RuntimeOutput(serializers.Serializer):
    version = VersionOutput(allow_null=True)
    current_version_id = serializers.IntegerField(allow_null=True)
    submission = SubmissionOutput(allow_null=True)
    result = ResultOutput(allow_null=True)
    progress_percent = serializers.IntegerField()
    is_completed = serializers.BooleanField()
