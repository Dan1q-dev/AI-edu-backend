from django.db import transaction
from .models import LearningTrack, Course, Module, Lesson, LearningItem


def set_item_positions(items):
    # Move to unused positions first to avoid the per-module unique constraint.
    if not items or all(item.position == index for index, item in enumerate(items)):
        return
    offset = max(item.position for item in items) + len(items) + 1
    for index, item in enumerate(items):
        LearningItem.objects.filter(pk=item.pk).update(position=offset + index)
    for position, item in enumerate(items):
        LearningItem.objects.filter(pk=item.pk).update(position=position)
        if item.lesson_id:
            Lesson.objects.filter(pk=item.lesson_id).update(position=position)
        item.position = position


def order_module_items(module_id):
    items = list(LearningItem.objects.filter(module_id=module_id).order_by('position', 'id'))
    items.sort(key=lambda item: item.type == LearningItem.Type.TEST)
    set_item_positions(items)


@transaction.atomic
def delete_item(item):
    Module.objects.select_for_update().get(pk=item.module_id)
    item.delete()
    order_module_items(item.module_id)


@transaction.atomic
def delete_content(instance):
    if not isinstance(instance, (Lesson, Module, Course, LearningTrack)):
        raise TypeError('Unsupported content type')
    if isinstance(instance, Lesson):
        Module.objects.select_for_update().get(pk=instance.module_id)
    instance.delete()
    if isinstance(instance, Lesson):
        order_module_items(instance.module_id)
