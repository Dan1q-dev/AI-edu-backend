from django.db import transaction
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from common.permissions import is_admin, IsPlatformAdmin
from apps.education.access import can_access_lesson
from apps.education.models import Lesson
from .models import LessonBlock
from .serializers import BlockSerializer

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
