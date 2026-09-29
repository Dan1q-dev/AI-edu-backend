import os
from django.contrib.auth.hashers import make_password
from django.db import migrations


def create_admin_user(apps, schema_editor):
    User = apps.get_model('accounts', 'User')

    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@aiedu.kz').strip().lower()
    admin_password = os.environ.get('ADMIN_PASSWORD', 'aiedu123')

    user, created = User.objects.get_or_create(
        email=admin_email,
        defaults={
            'password': make_password(admin_password),
            'role': 'ADMIN',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
            'first_name': 'Admin',
            'last_name': 'AI-edu',
        },
    )

    if not created:
        user.role = 'ADMIN'
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.password = make_password(admin_password)
        user.save(update_fields=['role', 'is_staff', 'is_superuser', 'is_active', 'password'])


def remove_admin_user(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@aiedu.kz').strip().lower()
    User.objects.filter(email=admin_email).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_admin_user, reverse_code=remove_admin_user),
    ]
