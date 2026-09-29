from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('education', '0004_course_hierarchy')]
    operations = [
        migrations.AlterField(
            model_name='course',
            name='slug',
            field=models.SlugField(allow_unicode=True, blank=True, max_length=220, unique=True),
        ),
    ]
