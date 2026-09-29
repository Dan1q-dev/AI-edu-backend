from django.db import migrations, models


TRACKS = (
    ('Базовая траектория 1', 'Основная базовая траектория обучения.'),
    ('Базовая траектория 2', 'Дополнительная базовая траектория обучения.'),
)


def create_default_tracks(apps, schema_editor):
    LearningTrack = apps.get_model('education', 'LearningTrack')
    database = schema_editor.connection.alias

    for title, description in TRACKS:
        track, _ = LearningTrack.objects.using(database).get_or_create(
            title=title,
            defaults={
                'description': description,
                'is_published': True,
                'is_active': True,
                'is_system': True,
            },
        )
        if not track.is_system:
            LearningTrack.objects.using(database).filter(pk=track.pk).update(is_system=True)


class Migration(migrations.Migration):
    dependencies = [('education', '0005_course_slug_unicode')]

    operations = [
        migrations.AddField(
            model_name='learningtrack',
            name='is_system',
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.RunPython(create_default_tracks, migrations.RunPython.noop),
    ]
