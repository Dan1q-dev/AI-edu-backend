from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from common.permissions import IsPlatformAdmin
from apps.education.access import can_access_item
from apps.education.views import item_queryset
from .registry import registry
from .serializers import DraftInput, SubmissionInput, VersionOutput, ManifestOutput, DraftOutput, RuntimeOutput
from .services import save_draft, publish_draft, start_submission, submit, runtime_state


def practice_item(request, short_id):
    item = item_queryset(request).filter(short_id=short_id, type='PRACTICE').first()
    if not item:
        raise NotFound()
    if not can_access_item(request.user, item):
        raise PermissionDenied('Сначала завершите предыдущий модуль')
    return item


class PracticeCatalogView(generics.GenericAPIView):
    serializer_class = ManifestOutput
    pagination_class = None

    @extend_schema(responses=ManifestOutput(many=True))
    def get(self, request):
        return Response(registry.manifests())


class PracticeDraftView(generics.GenericAPIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = DraftInput

    @extend_schema(responses=DraftOutput)
    def get(self, request, short_id):
        item = practice_item(request, short_id)
        versions = item.practice.versions.all() if item.practice_id else []
        draft = next((version for version in reversed(list(versions)) if version.status == 'DRAFT'), None)
        return Response({'draft': VersionOutput(draft).data if draft else None,
                         'published': VersionOutput(item.practice_version).data if item.practice_version_id else None,
                         'versions': VersionOutput(versions, many=True).data})

    @extend_schema(responses=VersionOutput)
    def put(self, request, short_id):
        item = practice_item(request, short_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(VersionOutput(save_draft(item, request.user, serializer.validated_data)).data)

    @extend_schema(request=None, responses=VersionOutput)
    def post(self, request, short_id):
        item = practice_item(request, short_id)
        return Response(VersionOutput(publish_draft(item)).data)


class ItemPracticeView(generics.GenericAPIView):
    serializer_class = SubmissionInput

    @extend_schema(responses=RuntimeOutput)
    def get(self, request, short_id):
        return Response(runtime_state(request.user, practice_item(request, short_id)))

    @extend_schema(responses=RuntimeOutput)
    def post(self, request, short_id):
        item = practice_item(request, short_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        submission = submit(request.user, item, data['submission_id'], data['submission_data'])
        return Response(runtime_state(request.user, item, submission))


class PracticeStartView(generics.GenericAPIView):
    serializer_class = RuntimeOutput

    @extend_schema(request=None, responses=RuntimeOutput)
    def post(self, request, short_id):
        item = practice_item(request, short_id)
        return Response(runtime_state(request.user, item, start_submission(request.user, item)))


class PracticeHistoryView(generics.GenericAPIView):
    serializer_class = RuntimeOutput

    @extend_schema(responses=RuntimeOutput(many=True))
    def get(self, request, short_id):
        from apps.education.models import PracticeSubmission
        item = practice_item(request, short_id)
        rows = PracticeSubmission.objects.select_related('practice_version__practice_definition', 'result').filter(
            user=request.user, item=item).order_by('-started_at', '-pk')
        page = self.paginate_queryset(rows)
        return self.get_paginated_response([runtime_state(request.user, item, row) for row in page])
