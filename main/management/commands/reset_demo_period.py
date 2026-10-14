import getpass
import json
from datetime import timedelta

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from main.management.demo_data import inspect_seed_state
from main.management.demo_safety import require_demo_database
from main.models import DemoSettings

AUDIT_USERNAME = '__waterstation_demo_audit__'


def configuration(instance):
    if instance is None:
        return None
    return {
        'start': instance.demo_start_date.isoformat(),
        'days': instance.demo_duration_days,
        'expires': (instance.demo_start_date + timedelta(days=instance.demo_duration_days)).isoformat(),
        'active': instance.is_active,
    }


class Command(BaseCommand):
    help = 'Preview or explicitly confirm a fresh demo period in the isolated development database only.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, required=True, help='Requested duration, from 1 to 365 days.')
        flags = parser.add_mutually_exclusive_group()
        flags.add_argument('--dry-run', action='store_true', help='Preview without saving settings or audit entries.')
        flags.add_argument('--confirm', action='store_true', help='Explicitly authorize this isolated demo-only reset.')

    def handle(self, *args, **options):
        if not 1 <= options['days'] <= 365:
            raise CommandError('--days must be an integer from 1 to 365.')
        path = require_demo_database()
        self.stdout.write(f'Isolated demo database: {path}')
        with transaction.atomic():
            # A renamed/copied normal database with real business data is not a demo.
            inspect_seed_state()
            instances = list(DemoSettings.objects.select_for_update())
            if len(instances) > 1:
                raise CommandError('Multiple DemoSettings records exist; refusing ambiguous reset.')
            instance = instances[0] if instances else None
            before = configuration(instance)
            now = timezone.now()
            self.stdout.write('Current demo configuration: ' + json.dumps(before, sort_keys=True))
            proposed = {'start': now.isoformat(), 'days': options['days'], 'expires': (now + timedelta(days=options['days'])).isoformat(), 'active': True}
            self.stdout.write('Proposed demo configuration: ' + json.dumps(proposed, sort_keys=True))
            self.stdout.write('This starts a fresh period now. Existing application access restrictions are unchanged.')
            if options['dry_run']:
                self.stdout.write('DRY RUN: no settings, accounts, or audit entries were written.')
                return
            if not options['confirm']:
                raise CommandError('Changes require --confirm. Use --dry-run to preview first.')
            actor, _ = get_user_model().objects.get_or_create(
                username=AUDIT_USERNAME,
                defaults={'password': '!', 'is_active': False, 'is_staff': False, 'is_superuser': False},
            )
            if actor.has_usable_password() or actor.is_active or actor.is_staff or actor.is_superuser:
                raise CommandError('Audit account name is already in use; refusing to modify any account.')
            created = instance is None
            if created:
                instance = DemoSettings()
            instance.demo_start_date = now
            instance.demo_duration_days = options['days']
            instance.is_active = True
            instance.full_clean()
            instance.save()
            LogEntry.objects.create(
                user=actor, content_type=ContentType.objects.get_for_model(DemoSettings),
                object_id=str(instance.pk), object_repr='Isolated development demo period',
                action_flag=ADDITION if created else CHANGE,
                change_message=json.dumps({'operation': 'reset_demo_period', 'operator': getpass.getuser(), 'database': str(path), 'before': before, 'after': configuration(instance)}, sort_keys=True),
            )
            self.stdout.write(self.style.SUCCESS('Demo period reset and database audit entry saved.'))
