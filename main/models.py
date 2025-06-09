from django.db import models
from django.utils import timezone

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

    def __str__(self):
        return self.name


# models.py

class Transaction(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=0)  # or FloatField
    price_per_gallon = models.DecimalField(max_digits=10, decimal_places=2)  # or FloatField
    created_at = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(max_length=50)
    payment_method = models.CharField(max_length=50)
    # other fields...

    @property
    def total_amount(self):
        return self.quantity * self.price_per_gallon
