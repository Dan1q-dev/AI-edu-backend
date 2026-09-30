from django.db import transaction
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from common.permissions import is_admin, IsPlatformAdmin
from apps.education.access import can_access_lesson
from apps.education.models import Lesson
from .models import LessonBlock
from .serializers import BlockSerializer, LessonDraftSerializer


class LessonDraftView(GenericAPIView):
    """Private editable snapshot; publishing explicitly copies it to live rows."""
    serializer_class = LessonDraftSerializer

    def get_lesson(self, request, short_id):
        if not is_admin(request.user):
            raise PermissionDenied()
        lesson = Lesson.objects.prefetch_related('blocks').filter(short_id=short_id).first()
        if not lesson:
            raise NotFound()
        return lesson

    def get(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        data = lesson.draft_data
        if data is None:
            data = {
                'title': lesson.title,
                'description': lesson.description,
                'blocks': BlockSerializer(lesson.blocks.all(), many=True).data,
            }
        else:
            data = {**data, 'blocks': [
                {**block, 'media_url': f"/api/v1/media/{block['media']}/" if block.get('media') else None}
                for block in data.get('blocks', [])
            ]}
        return Response(data)

    @transaction.atomic
    def put(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
        data = request.data
        if not isinstance(data, dict) or not isinstance(data.get('blocks'), list):
            raise ValidationError({'blocks': 'Ожидается список блоков'})
        if len(data['blocks']) > 100:
            raise ValidationError({'blocks': 'Максимум 100 блоков'})
        blocks = data['blocks']
        positions = [block.get('position') for block in blocks if isinstance(block, dict)]
        if len(positions) != len(blocks) or positions != list(range(len(blocks))):
            raise ValidationError({'position': 'Позиции блоков должны идти подряд от нуля'})
        serializer = BlockSerializer(data=blocks, many=True)
        serializer.is_valid(raise_exception=True)
        normalized_blocks = [
            {**block, 'media': block['media'].pk if block.get('media') else None}
            for block in serializer.validated_data
        ]
        title = data.get('title', lesson.title)
        description = data.get('description', lesson.description)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValidationError({'title': 'Укажите название длиной до 200 символов'})
        if not isinstance(description, str):
            raise ValidationError({'description': 'Описание должно быть текстом'})
        lesson.draft_data = {
            'title': title.strip(),
            'description': description,
            'blocks': normalized_blocks,
        }
        lesson.save(update_fields=['draft_data'])
        return Response(lesson.draft_data)

    @transaction.atomic
    def post(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
        if lesson.draft_data is not None:
            data = lesson.draft_data
            lesson.title = data['title']
            lesson.description = data['description']
            serializer = BlockSerializer(data=data['blocks'], many=True)
            serializer.is_valid(raise_exception=True)
            lesson.blocks.all().delete()
            LessonBlock.objects.bulk_create([
                LessonBlock(lesson=lesson, **block) for block in serializer.validated_data
            ])
        lesson.status = Lesson.Status.PUBLISHED
        lesson.save(update_fields=['title', 'description', 'status', 'updated_at'])
        if hasattr(lesson, 'learning_item'):
            item = lesson.learning_item
            item.title = lesson.title
            item.description = lesson.description
            item.status = 'PUBLISHED'
            item.save(update_fields=['title', 'description', 'status', 'updated_at'])
        return Response({'status': lesson.status, 'title': lesson.title})

class BlocksView(GenericAPIView):
    serializer_class = BlockSerializer
    def get_lesson(self, request, short_id):
        lesson = Lesson.objects.select_related('module__course__learning_track').filter(short_id=short_id).first()
        if not lesson:
            raise NotFound()
        if not can_access_lesson(request.user, lesson):
            raise PermissionDenied()
        return lesson

    def get(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        return Response(BlockSerializer(lesson.blocks.all(), many=True).data)

    @transaction.atomic
    def put(self, request, short_id):
        if not is_admin(request.user):
            raise PermissionDenied()
        lesson = self.get_lesson(request, short_id)
        Lesson.objects.select_for_update().get(pk=lesson.pk)
        if not isinstance(request.data, list):
            raise ValidationError({'blocks': 'Ожидается список блоков'})
        if len(request.data) > 100:
            raise ValidationError({'blocks': 'Максимум 100 блоков'})
        positions = [b.get('position') for b in request.data if isinstance(b, dict)]
        if positions != list(range(len(positions))) or len(positions) != len(request.data):
            raise ValidationError({'position': 'Позиции должны идти подряд от нуля'})
        serializer = BlockSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        lesson.blocks.all().delete()
        blocks = [LessonBlock(lesson=lesson, **b) for b in serializer.validated_data]
        LessonBlock.objects.bulk_create(blocks)
        return Response(BlockSerializer(lesson.blocks.all(), many=True).data)
