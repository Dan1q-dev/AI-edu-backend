import time
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, close_old_connections
from apps.activities.workspace.worker import claim_next_operation, execute_operation, recover_expired_operations


class Command(BaseCommand):
    help = 'Process workspace AI operations; PostgreSQL is required for continuous/concurrent workers.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Recover leases and process at most one operation, then exit')
        parser.add_argument('--poll-interval', type=float, default=2.0)

    def handle(self, *args, **options):
        if not 0.1 <= options['poll_interval'] <= 30:
            raise CommandError('--poll-interval must be between 0.1 and 30 seconds')
        if connection.vendor != 'postgresql' and not options['once']:
            raise CommandError('Continuous workers require PostgreSQL; use --once for isolated SQLite development')
        try:
            while True:
                close_old_connections()
                recovered = recover_expired_operations()
                if recovered:
                    self.stdout.write(f'Recovered {recovered} expired operation(s)')
                operation = claim_next_operation()
                if operation:
                    execute_operation(operation)
                    operation.refresh_from_db()
                    self.stdout.write(f'Operation {operation.pk}: {operation.status} {operation.error_code}')
                if options['once']:
                    return
                if operation is None:
                    time.sleep(options['poll_interval'])
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped')
