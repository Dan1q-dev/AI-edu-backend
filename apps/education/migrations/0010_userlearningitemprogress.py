from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('education', '0009_migrate_learning_items'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.CreateModel(
        name='UserLearningItemProgress',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('progress_percent', models.PositiveSmallIntegerField(default=0)),
            ('is_completed', models.BooleanField(default=False)),
            ('started_at', models.DateTimeField(auto_now_add=True)),
            ('completed_at', models.DateTimeField(blank=True, null=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('learning_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_progress', to='education.learningitem')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='learning_progress', to=settings.AUTH_USER_MODEL)),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('user', 'learning_item'), name='unique_user_learning_item_progress')]},
    )]
