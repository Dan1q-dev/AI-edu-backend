import secrets
from django.db import migrations, models
import django.db.models.deletion
from apps.education.models import generate_short_id


def migrate_legacy_structure(apps, schema_editor):
    Track = apps.get_model('education', 'LearningTrack')
    Course = apps.get_model('education', 'Course')
    Module = apps.get_model('education', 'Module')
    alias = schema_editor.connection.alias
    for track in Track.objects.using(alias).order_by('pk').iterator():
        base = ''.join(c.lower() if c.isalnum() else '-' for c in track.title).strip('-')[:200] or 'legacy-course'
        base = '-'.join(part for part in base.split('-') if part)
        slug, suffix = base, 2
        while Course.objects.using(alias).filter(slug=slug).exists():
            slug = f'{base[:210-len(str(suffix))]}-{suffix}'
            suffix += 1
        short_id = generate_short_id()
        Course.objects.using(alias).create(
            learning_track=None,
            title=track.title,
            slug=slug,
            description=track.description,
            cover_id=track.cover_id,
            position=track.pk,
            is_published=track.is_published,
            created_at=track.created_at,
            updated_at=track.updated_at,
            short_id=short_id,
        )
        course = Course.objects.using(alias).get(slug=slug)
        Module.objects.using(alias).filter(track_id=track.pk).update(course_id=course.pk)
        # Legacy rows may be courses or true learning tracks. Keep them intact and
        # unavailable for registration until an administrator explicitly maps them.
        Track.objects.using(alias).filter(pk=track.pk).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [('education', '0003_short_ids_remove_track_slug')]
    operations = [
        migrations.AddField(
            model_name='learningtrack', name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('short_id', models.CharField(default=generate_short_id, editable=False, max_length=10, unique=True)),
                ('title', models.CharField(max_length=200)),
                ('slug', models.SlugField(blank=True, max_length=220, unique=True)),
                ('description', models.TextField(blank=True)),
                ('position', models.PositiveIntegerField(default=0)),
                ('is_published', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cover', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='mediafiles.mediafile')),
                ('learning_track', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courses', to='education.learningtrack')),
            ],
            options={'ordering': ['position', 'id']},
        ),
        migrations.AddField(
            model_name='module', name='course',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='modules', to='education.course'),
        ),
        migrations.RunPython(migrate_legacy_structure, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='module', name='course',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='modules', to='education.course'),
        ),
        migrations.RemoveField(model_name='module', name='track'),
    ]
