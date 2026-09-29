from django.core.management.base import BaseCommand
from apps.mediafiles.models import MediaFile

class Command(BaseCommand):
    help = 'Show or delete media files not referenced by any lesson block or track cover'
    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true')
    def handle(self, *args, **options):
        unused = MediaFile.objects.filter(lessonblock__isnull=True, learningtrack__isnull=True, course__isnull=True).distinct()
        count = unused.count()
        if options['delete']:
            for media in unused.iterator():
                media.file.delete(save=False)
                media.delete()
        self.stdout.write(f'{count} unused files' + (' deleted' if options['delete'] else ' found; use --delete to remove'))
