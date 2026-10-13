from django.db import migrations


RENAMES = (
    ('Базовая траектория 1', 'Траектория 1: для IT-специальностей'),
    ('Базовая траектория 2', 'Траектория 2: для не IT-специальностей'),
)


def rename_default_tracks(apps, schema_editor):
    LearningTrack = apps.get_model('education', 'LearningTrack')
    database = schema_editor.connection.alias

    for old_title, new_title in RENAMES:
        LearningTrack.objects.using(database).filter(title=old_title).update(title=new_title)


def restore_default_track_names(apps, schema_editor):
    LearningTrack = apps.get_model('education', 'LearningTrack')
    database = schema_editor.connection.alias

    for old_title, new_title in RENAMES:
        LearningTrack.objects.using(database).filter(title=new_title).update(title=old_title)


class Migration(migrations.Migration):
    dependencies = [('education', '0015_alter_practicesubmission_practice_version')]

    operations = [
        migrations.RunPython(rename_default_tracks, restore_default_track_names),
    ]
