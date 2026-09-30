from rest_framework import serializers
from .models import LessonBlock

class BlockSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()
    class Meta:
        model = LessonBlock
        fields = ['id', 'type', 'position', 'content', 'media', 'media_url', 'config']
        read_only_fields = ['id', 'media_url']
    def get_media_url(self, obj) -> str | None:
        return f'/api/v1/media/{obj.media_id}/' if obj.media_id else None
    def validate(self, data):
        kind = data.get('type')
        if kind == 'TEXT' and (not data.get('content', '').strip() or data.get('media')):
            raise serializers.ValidationError('TEXT требует текст без изображения')
        if kind == 'IMAGE' and not data.get('media'):
            raise serializers.ValidationError('IMAGE требует изображение')
        if len(data.get('content', '')) > 50000:
            raise serializers.ValidationError('Текст слишком длинный')
        return data


class LessonDraftSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, required=False)
    blocks = BlockSerializer(many=True)
