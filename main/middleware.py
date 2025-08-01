from django.shortcuts import render
from django.utils import timezone
from .models import DemoSettings

class DemoExpirationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if demo is expired
        try:
            demo_settings = DemoSettings.objects.first()
            if demo_settings and demo_settings.is_expired():
                return render(request, 'main/demo_expired.html', {
                    'expiry_date': demo_settings.demo_start_date + timezone.timedelta(days=demo_settings.demo_duration_days)
                })
        except DemoSettings.DoesNotExist:
            pass

        response = self.get_response(request)
        return response