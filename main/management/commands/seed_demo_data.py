from django.core.management.base import BaseCommand
from django.db import transaction

from main.management.demo_data import create_seed, inspect_seed_state, planned_summary
from main.management.demo_safety import require_demo_database


class Command(BaseCommand):
    help = 'Seed a deterministic fictional dataset only in the explicitly isolated demo SQLite database.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Inspect and preview without creating any records.')

    def handle(self, *args, **options):
        path = require_demo_database()
        self.stdout.write(f'Isolated demo database: {path}')
        with transaction.atomic():
            existing = inspect_seed_state()
            if existing:
                self.stdout.write('Created: 0 customers, 0 inventory items, 0 transactions, 0 stock logs. Existing verified demo records: 12 customers, 3 items, 40 transactions, 3 logs.')
            elif options['dry_run']:
                self.stdout.write('DRY RUN: would create 12 customers, 3 inventory items, 40 transactions, 3 stock logs. Existing demo records: 0. Nothing written.')
            else:
                create_seed()
                self.stdout.write(self.style.SUCCESS('Created: 12 customers, 3 inventory items, 40 transactions, 3 stock logs. Existing demo records: 0.'))
            for line in planned_summary():
                self.stdout.write(line)
