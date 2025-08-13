from .models import DemoSettings

def demo_context(request):
    try:
        demo_settings = DemoSettings.objects.first()
        if demo_settings:
            return {
                'demo_days_remaining': demo_settings.days_remaining(),
                'demo_expired': demo_settings.is_expired  # ✅ property, no ()
            }
    except DemoSettings.DoesNotExist:
        pass
    
    return {
        'demo_days_remaining': 0,
        'demo_expired': True
    }
