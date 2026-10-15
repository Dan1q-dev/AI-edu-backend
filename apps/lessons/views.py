from django.db import transaction
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from common.permissions import is_admin, IsPlatformAdmin
from apps.education.access import can_access_lesson
from apps.education.models import Lesson
from apps.mediafiles.models import MediaFile
from .models import LessonBlock, LessonAttachment
from .serializers import AttachmentSerializer, BlockSerializer, LessonDraftSerializer


class LessonDraftView(GenericAPIView):
    """Private editable snapshot; publishing explicitly copies it to live rows."""
    serializer_class = LessonDraftSerializer

    def get_lesson(self, request, short_id):
        if not is_admin(request.user):
            raise PermissionDenied()
        lesson = Lesson.objects.prefetch_related('blocks', 'attachments__media').filter(short_id=short_id).first()
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
                'attachments': [attachment_data(item.media) for item in lesson.attachments.all()],
            }
        else:
            data = {**data, 'attachments': attachment_list(data.get('attachments', [])), 'blocks': [
                {**block, 'media_url': f"/api/v1/media/{block['media']}/" if block.get('media') else None}
                for block in data.get('blocks', [])
            ]}
        return Response({**data, 'revision': lesson.draft_revision})

    @transaction.atomic
    def put(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
        data = request.data
        if isinstance(data, dict) and 'revision' in data and (type(data['revision']) is not int or data['revision'] != lesson.draft_revision):
            return Response({'detail': 'Черновик изменён в другом окне. Скопируйте свои изменения и перезагрузите страницу.', 'code': 'draft_conflict'}, status=409)
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
        attachment_ids = data.get('attachments', [])
        if not isinstance(attachment_ids, list) or len(attachment_ids) > 20:
            raise ValidationError({'attachments': 'Можно прикрепить не более 20 файлов'})
        attachment_ids = [item.get('media') if isinstance(item, dict) else item for item in attachment_ids]
        if any(type(pk) is not int for pk in attachment_ids) or len(set(attachment_ids)) != len(attachment_ids):
            raise ValidationError({'attachments': 'Некорректный список файлов'})
        if MediaFile.objects.filter(pk__in=attachment_ids).count() != len(attachment_ids):
            raise ValidationError({'attachments': 'Один из файлов не найден'})
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
            'attachments': attachment_ids,
        }
        lesson.draft_revision += 1
        lesson.save(update_fields=['draft_data', 'draft_revision'])
        return Response({**lesson.draft_data, 'attachments': attachment_list(attachment_ids), 'revision': lesson.draft_revision})

    @transaction.atomic
    def post(self, request, short_id):
        lesson = self.get_lesson(request, short_id)
        lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
        if isinstance(request.data, dict) and 'revision' in request.data and request.data['revision'] != lesson.draft_revision:
            return Response({'detail': 'Черновик изменён в другом окне. Обновите страницу перед публикацией.', 'code': 'draft_conflict'}, status=409)
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
            attachment_ids = data.get('attachments', [])
            if MediaFile.objects.filter(pk__in=attachment_ids).count() != len(attachment_ids):
                raise ValidationError({'attachments': 'Один из файлов не найден'})
            lesson.attachments.all().delete()
            LessonAttachment.objects.bulk_create([
                LessonAttachment(lesson=lesson, media_id=media_id, position=position)
                for position, media_id in enumerate(attachment_ids)
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


def attachment_data(media):
    return {'media': media.pk, 'name': media.original_name, 'size': media.size,
            'url': f'/api/v1/media/{media.pk}/download/'}


def attachment_list(ids):
    media_by_id = MediaFile.objects.in_bulk(ids)
    return [attachment_data(media_by_id[pk]) for pk in ids if pk in media_by_id]


class AttachmentsView(GenericAPIView):
    serializer_class = AttachmentSerializer
    def get(self, request, short_id):
        lesson = Lesson.objects.select_related('module__course__learning_track').filter(short_id=short_id).first()
        if not lesson:
            raise NotFound()
        if not can_access_lesson(request.user, lesson):
            raise PermissionDenied()
        return Response([attachment_data(item.media) for item in lesson.attachments.select_related('media')])

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
