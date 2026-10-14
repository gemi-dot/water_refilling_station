

# Register your models here.
from django.contrib import admin
from .models import Customer, InventoryItem, Transaction

from .models import DemoSettings
from .forms import InventoryItemForm, InventoryMetadataForm
from .inventory import deletion_reason

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


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'unit', 'stock_in', 'stock_out', 'current_stock']

    def get_form(self, request, obj=None, **kwargs):
        kwargs['form'] = InventoryMetadataForm if obj else InventoryItemForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        fields = ['stock_in', 'stock_out']
        if deletion_reason(obj):
            fields.append('unit')
        return fields

    def get_deleted_objects(self, objs, request):
        items = list(objs)
        deleted, counts, permissions, protected = super().get_deleted_objects(items, request)
        for item in items:
            reason = deletion_reason(item)
            if reason:
                protected.append(f'{item.name}: {reason}')
        return deleted, counts, permissions, protected


admin.site.register(Transaction)
