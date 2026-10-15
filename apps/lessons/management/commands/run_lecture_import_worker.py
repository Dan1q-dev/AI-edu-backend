import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from apps.lessons.importing.worker import claim, execute


class Command(BaseCommand):
    help = 'Process lecture file imports (install requirements-import.txt and Tesseract first).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one job, then exit.')

    def handle(self, *args, **options):
        self.stdout.write('Lecture import worker ready')
        try:
            while True:
                close_old_connections()
                job = claim()
                if job:
                    self.stdout.write(f'Processing {job.pk} (attempt {job.attempts})')
                    execute(job)
                if options['once']:
                    return
                if not job:
                    time.sleep(2)
        except KeyboardInterrupt:
            return
