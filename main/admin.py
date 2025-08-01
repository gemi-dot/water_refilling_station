

# Register your models here.
from django.contrib import admin
from .models import Customer, InventoryItem, Transaction

from .models import DemoSettings

@admin.register(DemoSettings)
class DemoSettingsAdmin(admin.ModelAdmin):
    list_display = ['demo_start_date', 'demo_duration_days', 'days_remaining', 'is_expired', 'is_active']
    readonly_fields = ['created_at', 'days_remaining', 'is_expired']
    
    def days_remaining(self, obj):
        return obj.days_remaining()
    days_remaining.short_description = 'Days Remaining'
    
    def is_expired(self, obj):
        return obj.is_expired()
    is_expired.boolean = True
    is_expired.short_description = 'Expired'

admin.site.register(Customer)
admin.site.register(InventoryItem)
admin.site.register(Transaction)
