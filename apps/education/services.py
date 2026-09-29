from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import LearningTrack, Course, Module, Lesson

@transaction.atomic
def delete_content(instance):
    from apps.assessments.models import TestAttempt, Test
    from apps.lessons.models import LessonBlock
    from apps.activities.models import PracticeDefinition
    if isinstance(instance, Lesson):
        lessons = [instance]
    elif isinstance(instance, Module):
        lessons = list(instance.lessons.all())
    elif isinstance(instance, Course):
        lessons = list(Lesson.objects.filter(module__course=instance))
    elif isinstance(instance, LearningTrack):
        lessons = list(Lesson.objects.filter(module__course__learning_track=instance))
    else:
        raise TypeError('Unsupported content type')
    ids = [lesson.pk for lesson in lessons]
    if TestAttempt.objects.filter(test__lesson_id__in=ids).exists():
        raise ValidationError({'detail': 'Материал содержит результаты студентов и не может быть удалён'})
    LessonBlock.objects.filter(lesson_id__in=ids).delete()
    PracticeDefinition.objects.filter(lesson_id__in=ids).delete()
    Test.objects.filter(lesson_id__in=ids).delete()
    Lesson.objects.filter(pk__in=ids).delete()
    if isinstance(instance, (Course, LearningTrack)):
        modules = Module.objects.filter(course=instance) if isinstance(instance, Course) else Module.objects.filter(course__learning_track=instance)
        modules.delete()
    if isinstance(instance, LearningTrack):
        Course.objects.filter(learning_track=instance).delete()
    if not isinstance(instance, Lesson):
        instance.delete()
