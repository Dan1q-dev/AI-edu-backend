import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_create_admin_user'),
        ('education', '0004_course_hierarchy'),
    ]
    operations = [
        migrations.AddField(
            model_name='user',
            name='learning_track',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='students', to='education.learningtrack'),
        ),
    ]
