from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from .models import DemoSettings


class DemoExpirationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Get demo settings safely (singleton if available)
        demo_settings = getattr(DemoSettings, "get_instance", None)
        demo_settings = demo_settings() if callable(demo_settings) else DemoSettings.objects.first()

        if demo_settings and demo_settings.is_expired:  # ✅ property, no parentheses
            return render(
                request,
                'main/demo_expired.html',
                {
                    'expiry_date': demo_settings.demo_start_date + timedelta(days=demo_settings.demo_duration_days)
                }
            )

        return self.get_response(request)
