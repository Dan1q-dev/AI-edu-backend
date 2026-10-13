from copy import deepcopy
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError
from apps.accounts.models import User
from apps.education.models import PracticeSubmission
from apps.activities.models import WorkspaceDocument, WorkspaceMessage, WorkspaceOperation
from apps.activities.registry import registry
from apps.activities.services import start_submission


class Conflict(APIException):
    status_code = 409
    default_detail = 'Документ изменился или операция уже выполняется'
    default_code = 'workspace_conflict'


class AIUnavailable(APIException):
    status_code = 503
    default_detail = 'AI API не настроен'
    default_code = 'ai_unavailable'


def workspace_plugin(submission):
    version = submission.practice_version
    plugin = registry.get(version.practice_definition.practice_type, version.plugin_version)
    if not getattr(plugin, 'workspace_type', None):
        raise ValidationError({'detail': 'Эта практика не поддерживает workspace'})
    return plugin


def ensure_mutable(submission):
    if submission.status != 'IN_PROGRESS':
        raise Conflict('Попытка уже сдана. Начните новую попытку')


def locked_document(user, document):
    # Match the Practice Engine lock order, including concurrent submission.
    user = User.objects.select_for_update().get(pk=user.pk)
    submission = PracticeSubmission.objects.select_for_update(of=('self',)).select_related(
        'practice_version__practice_definition', 'item__module__course__learning_track').get(pk=document.submission_id)
    document = WorkspaceDocument.objects.select_for_update().get(pk=document.pk, owner=user)
    from apps.education.access import can_access_item
    if not can_access_item(user, submission.item):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('Учебный элемент недоступен')
    ensure_mutable(submission)
    return document, workspace_plugin(submission)


@transaction.atomic
def create_document(user, item, parameters):
    # Validate against the pinned version if an attempt already exists.
    user = User.objects.select_for_update().get(pk=user.pk)
    active = PracticeSubmission.objects.filter(user=user, item=item, status='IN_PROGRESS').select_related(
        'practice_version__practice_definition').first()
    version = active.practice_version if active else item.practice_version
    if not version:
        raise ValidationError({'detail': 'Практическая работа ещё не настроена'})
    plugin = registry.get(version.practice_definition.practice_type, version.plugin_version)
    if not getattr(plugin, 'workspace_type', None):
        raise ValidationError({'detail': 'Эта практика не поддерживает workspace'})
    parameters = plugin.validate_workspace_parameters(parameters)
    submission = start_submission(user, item)
    from apps.education.access import can_access_item
    if not can_access_item(user, submission.item):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('Учебный элемент недоступен')
    plugin = workspace_plugin(submission)
    parameters = plugin.validate_workspace_parameters(parameters)
    document, created = WorkspaceDocument.objects.get_or_create(submission=submission, defaults={
        'owner': user, 'document_type': plugin.workspace_type,
        'schema_version': plugin.workspace_schema_version, 'parameters': parameters})
    return document, created


@transaction.atomic
def update_document(user, document, data):
    document, plugin = locked_document(user, document)
    if document.revision != data['revision']:
        raise Conflict('Ревизия документа устарела')
    if 'parameters' in data:
        document.parameters = plugin.validate_workspace_parameters(data['parameters'])
    if 'content' in data:
        document.content = plugin.validate_workspace_content(data['content'])
    document.revision += 1
    document.save(update_fields=['parameters', 'content', 'revision', 'updated_at'])
    return document


@transaction.atomic
def create_operation(user, document, data):
    document, plugin = locked_document(user, document)
    existing = document.operations.filter(request_id=data['request_id']).first()
    if existing:
        if (existing.kind != data['kind'] or existing.base_revision != data['revision'] or
                existing.input_data['prompt'] != data['prompt']):
            raise Conflict('request_id уже использован с другим запросом')
        return existing
    if document.revision != data['revision']:
        raise Conflict('Ревизия документа устарела')
    if document.operations.filter(status__in=['PENDING', 'RUNNING']).exists():
        raise Conflict('Для документа уже выполняется AI-операция')
    if not settings.AI_BASE_URL or not settings.AI_MODEL:
        raise AIUnavailable()
    parameters = plugin.validate_workspace_parameters(document.parameters)
    operation = WorkspaceOperation.objects.create(document=document, request_id=data['request_id'],
        kind=data['kind'], base_revision=document.revision, model=settings.AI_MODEL,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
        input_data={'parameters': parameters, 'prompt': data['prompt'],
                    'messages': plugin.workspace_prompt(data['kind'], parameters, data['prompt'])})
    WorkspaceMessage.objects.create(document=document, operation=operation, role='user', text=data['prompt'])
    return operation


def prepare_submission(user, submission, data):
    if (not isinstance(data, dict) or set(data) != {'checks', 'document_id', 'document_revision'} or
            type(data['document_id']) is not int or type(data['document_revision']) is not int):
        raise ValidationError({'submission_data': 'Укажите checks, document_id и document_revision'})
    document = WorkspaceDocument.objects.select_for_update().filter(
        pk=data['document_id'], owner=user, submission=submission).first()
    if not document:
        raise NotFound()
    if document.revision != data['document_revision']:
        raise Conflict('Ревизия документа устарела')
    if document.operations.filter(status__in=['PENDING', 'RUNNING']).exists():
        raise Conflict('Дождитесь завершения AI-операции')
    plugin = workspace_plugin(submission)
    plugin.validate_workspace_parameters(document.parameters)
    plugin.validate_workspace_content(document.content)
    return {**deepcopy(data), 'document': {'parameters': deepcopy(document.parameters),
            'content': deepcopy(document.content), 'schema_version': document.schema_version}}
