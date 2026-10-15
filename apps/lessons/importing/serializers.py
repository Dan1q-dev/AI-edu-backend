from rest_framework import serializers


class ImportJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    size = serializers.IntegerField()
    status = serializers.ChoiceField(choices=['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'])
    stage = serializers.CharField()
    created_at = serializers.DateTimeField()
    source_url = serializers.CharField()
    error = serializers.CharField(allow_blank=True)
    result = serializers.JSONField(allow_null=True)


class ImportListSerializer(serializers.Serializer):
    jobs = ImportJobSerializer(many=True)
    ai_available = serializers.BooleanField()


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
