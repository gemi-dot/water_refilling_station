

# Register your models here.
from django.contrib import admin
from .models import Customer, InventoryItem, Transaction

admin.site.register(Customer)
admin.site.register(InventoryItem)
admin.site.register(Transaction)
