import secrets

from django.db import migrations, models
from apps.education.models import generate_short_id as default_short_id


def generate_short_id(used):
    while True:
        value = secrets.token_urlsafe(8)[:10]
        if value not in used:
            used.add(value)
            return value


def populate_short_ids(apps, schema_editor):
    for model_name in ('LearningTrack', 'Module', 'Lesson'):
        model = apps.get_model('education', model_name)
        used = set()
        for row in model.objects.using(schema_editor.connection.alias).order_by('pk').iterator():
            row.short_id = generate_short_id(used)
            row.save(update_fields=['short_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('education', '0002_alter_learningtrack_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='learningtrack',
            name='short_id',
            field=models.CharField(max_length=10, null=True),
        ),
        migrations.AddField(
            model_name='module',
            name='short_id',
            field=models.CharField(max_length=10, null=True),
        ),
        migrations.AddField(
            model_name='lesson',
            name='short_id',
            field=models.CharField(max_length=10, null=True),
        ),
        migrations.RunPython(populate_short_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='learningtrack',
            name='short_id',
            field=models.CharField(default=default_short_id, editable=False, max_length=10, unique=True),
        ),
        migrations.AlterField(
            model_name='module',
            name='short_id',
            field=models.CharField(default=default_short_id, editable=False, max_length=10, unique=True),
        ),
        migrations.AlterField(
            model_name='lesson',
            name='short_id',
            field=models.CharField(default=default_short_id, editable=False, max_length=10, unique=True),
        ),
        migrations.RemoveField(
            model_name='learningtrack',
            name='slug',
        ),
    ]
