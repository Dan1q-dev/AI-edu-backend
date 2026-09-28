from getpass import getpass
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from apps.accounts.models import User

class Command(BaseCommand):
    help = 'Create an ADMIN account without Django staff or superuser access'
    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
    def handle(self, *args, **options):
        email = options['email'].lower()
        if User.objects.filter(email=email).exists():
            raise CommandError('Email already exists')
        password = getpass('Password: ')
        if password != getpass('Repeat password: '):
            raise CommandError('Passwords differ')
        validate_password(password)
        User.objects.create_user(email=email, password=password, role='ADMIN')
        self.stdout.write(self.style.SUCCESS('Platform admin created'))
