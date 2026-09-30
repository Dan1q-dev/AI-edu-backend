from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Attempt = apps.get_model('assessments', 'TestAttempt')
    Progress = apps.get_model('education', 'UserLearningItemProgress')
    Item = apps.get_model('education', 'LearningItem')
    test_items = dict(Item.objects.filter(type='TEST', test_id__isnull=False).values_list('test_id', 'id'))
    for attempt in Attempt.objects.filter(passed=True, test_id__in=test_items).order_by('completed_at', 'id').iterator():
        Progress.objects.get_or_create(
            user_id=attempt.user_id, learning_item_id=test_items[attempt.test_id],
            defaults={'progress_percent': 100, 'is_completed': True, 'completed_at': attempt.completed_at or timezone.now()},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('education', '0010_userlearningitemprogress'),
        ('assessments', '0001_initial'),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
