from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('education', '0016_rename_default_learning_tracks')]
    operations = [migrations.AddField(model_name='lesson', name='draft_revision', field=models.PositiveIntegerField(default=0))]
