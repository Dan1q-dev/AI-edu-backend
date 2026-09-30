import secrets

from django.db import migrations


def migrate_items(apps, schema_editor):
    Lesson = apps.get_model('education', 'Lesson')
    LearningItem = apps.get_model('education', 'LearningItem')
    Test = apps.get_model('assessments', 'Test')
    Practice = apps.get_model('activities', 'PracticeDefinition')
    db = schema_editor.connection.alias
    module_ids = Lesson.objects.using(db).order_by().values_list('module_id', flat=True).distinct()
    for module_id in module_ids:
        position = 0
        lessons = Lesson.objects.using(db).filter(module_id=module_id).order_by('position', 'id')
        for lesson in lessons.iterator():
            # A lecture keeps the public Lesson ID. Blocks, media and drafts stay on that row.
            lecture = LearningItem.objects.using(db).create(
                short_id=lesson.short_id, module_id=module_id, type='LECTURE',
                title=lesson.title, description=lesson.description, position=position,
                status=lesson.status, lesson_id=lesson.pk,
            )
            LearningItem.objects.using(db).filter(pk=lecture.pk).update(
                created_at=lesson.created_at, updated_at=lesson.updated_at)
            position += 1
            test = Test.objects.using(db).filter(lesson_id=lesson.pk).first()
            if test:
                LearningItem.objects.using(db).create(
                    short_id=secrets.token_urlsafe(8)[:10], module_id=module_id,
                    type='TEST', title=test.title, description=test.description,
                    position=position, test_id=test.pk,
                    status='PUBLISHED' if test.is_published and lesson.status == 'PUBLISHED' else 'DRAFT',
                )
                position += 1
            for practice in Practice.objects.using(db).filter(lesson_id=lesson.pk).order_by('id'):
                LearningItem.objects.using(db).create(
                    short_id=secrets.token_urlsafe(8)[:10], module_id=module_id,
                    type='PRACTICE', title=practice.kind or f'Практика {practice.pk}',
                    position=position, practice_id=practice.pk,
                    status='PUBLISHED' if practice.is_enabled and lesson.status == 'PUBLISHED' else 'DRAFT',
                )
                position += 1


class Migration(migrations.Migration):
    dependencies = [('education', '0008_learningitem')]
    operations = [migrations.RunPython(migrate_items, migrations.RunPython.noop)]
