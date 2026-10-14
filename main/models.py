from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from datetime import timedelta
import math


import math

class Customer(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField()
    contact_number = models.CharField(max_length=20)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class InventoryItem(models.Model):
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=20)  # e.g., pcs, gallons
    stock_in = models.IntegerField(default=0)
    stock_out = models.IntegerField(default=0)

    def current_stock(self):
        return self.stock_in - self.stock_out

    def clean(self):
        super().clean()
        if self.stock_in < 0 or self.stock_out < 0 or self.stock_out > self.stock_in:
            raise ValidationError("Stock counts must be nonnegative and stock out cannot exceed stock in.")
        if self.pk:
            sold = self.transaction_set.aggregate(total=models.Sum('quantity'))['total'] or 0
            if self.stock_out < sold:
                raise ValidationError("Stock out cannot be less than the quantity in recorded sales.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                list(InventoryItem.objects.select_for_update().filter(pk=self.pk))
            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    

class Transaction(models.Model):
    DELIVERY_CHOICES = [
        ('walk-in', 'Walk-In'),
        ('delivery', 'Delivery'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('unpaid', 'Unpaid'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('online', 'Online'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price_per_gallon = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)  # Default value added
    created_at = models.DateTimeField(auto_now_add=True)
    delivery_type = models.CharField(max_length=10, choices=DELIVERY_CHOICES, default='walk-in')
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='paid')
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default='cash')
    collected_at_end_of_day = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be positive.'})
        if self.price_per_gallon is not None and self.price_per_gallon < 0:
            raise ValidationError({'price_per_gallon': 'Price cannot be negative.'})
        if self.inventory_item_id and self.quantity is not None:
            item = InventoryItem.objects.filter(pk=self.inventory_item_id).first()
            previous = Transaction.objects.filter(pk=self.pk).first() if self.pk else None
            credit = previous.quantity if previous and previous.inventory_item_id == self.inventory_item_id else 0
            if item and self.quantity > item.current_stock() + credit:
                raise ValidationError("Not enough stock available in inventory.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            previous = None
            if not self._state.adding:
                previous = Transaction.objects.select_for_update().get(pk=self.pk)
            # Respect partial saves: omitted sale fields retain their stored values.
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                if not update_fields:
                    return
                if previous:
                    for field in ('quantity', 'inventory_item', 'price_per_gallon'):
                        if field not in update_fields and f'{field}_id' not in update_fields:
                            setattr(self, field, getattr(previous, field))
                kwargs['update_fields'] = set(update_fields) | {'total_amount'}
            if self.quantity <= 0 or self.price_per_gallon < 0:
                raise ValidationError("Quantity must be positive and price cannot be negative.")
            item_ids = {self.inventory_item_id}
            if previous:
                item_ids.add(previous.inventory_item_id)
            # Consistent lock ordering avoids deadlocks when swapping items.
            list(InventoryItem.objects.select_for_update().filter(pk__in=item_ids).order_by('pk'))
            if previous:
                adjust_stock_out(previous.inventory_item_id, -previous.quantity)
            adjust_stock_out(self.inventory_item_id, self.quantity)
            self.total_amount = self.quantity * self.price_per_gallon
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            stored = Transaction.objects.select_for_update().get(pk=self.pk)
            return super(Transaction, stored).delete(*args, **kwargs)


def adjust_stock_out(item_id, change):
    """Conditional database updates protect balances even without row locks (SQLite)."""
    updated = InventoryItem.objects.filter(
        pk=item_id, stock_out__gte=max(0, -change),
        stock_in__gte=F('stock_out') + change,
    ).update(stock_out=F('stock_out') + change)
    if not updated:
        raise ValidationError("Not enough stock available, or inventory counts are inconsistent.")


@receiver(pre_delete, sender=Transaction)
def restore_deleted_sale_stock(sender, instance, **kwargs):
    # Also covers admin bulk deletion and customer cascade deletion.
    adjust_stock_out(instance.inventory_item_id, -instance.quantity)

        
class StockLog(models.Model):
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE)
    change = models.IntegerField()  # positive for stock in, negative for manual out
    date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.inventory_item.name} | Change: {self.change} | {self.date.strftime('%Y-%m-%d')}"


# Add to main/models.py


class DemoSettings(models.Model):
    demo_start_date = models.DateTimeField(default=timezone.now)
    demo_duration_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Demo Settings"

    def save(self, *args, **kwargs):
        # Enforce singleton: only one DemoSettings record
        if not self.pk and DemoSettings.objects.exists():
            raise ValueError("Only one DemoSettings instance is allowed.")
        super().save(*args, **kwargs)

    def days_remaining(self):
        """Return number of days remaining in the demo period."""
        expiry_date = self.demo_start_date + timedelta(days=self.demo_duration_days)
        remaining_seconds = (expiry_date - timezone.now()).total_seconds()
        if remaining_seconds <= 0:
            return 0
        return math.ceil(remaining_seconds / 86400)

    def has_expired(self):
        """True if demo period is over."""
        expiry_date = self.demo_start_date + timedelta(days=self.demo_duration_days)
        return timezone.now() >= expiry_date

    def check_and_deactivate(self):
        """Deactivate if expired."""
        if self.has_expired() and self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active"])

    @classmethod
    def get_instance(cls):
        """Always returns the singleton instance, creating it if needed."""
        instance, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                "demo_start_date": timezone.now(),
                "demo_duration_days": 30,
                "is_active": True
            }
        )
        return instance

    # ✅ Option A - property aliases
    @property
    def is_expired(self):
        """Alias to has_expired() for compatibility."""
        return self.has_expired()

    @property
    def days_left(self):
        """Alias to days_remaining() for compatibility."""
        return self.days_remaining()

    @property
    def is_still_active(self):
        """True if demo is active and not expired."""
        return self.is_active and not self.has_expired()









    
 