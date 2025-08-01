from django.core.management.base import BaseCommand
from main.models import DemoSettings

class Command(BaseCommand):
    help = 'Initialize demo settings'

    def handle(self, *args, **options):
        demo_settings, created = DemoSettings.objects.get_or_create(
            defaults={'demo_duration_days': 14, 'is_active': True}
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS('Demo settings created successfully')
            )
        else:
            self.stdout.write(
                self.style.WARNING('Demo settings already exist')
            )