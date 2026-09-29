from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('education', '0006_default_learning_tracks')]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='draft_data',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
