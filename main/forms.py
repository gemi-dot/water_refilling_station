from django import forms
from .models import Customer
from .models import Transaction
from .models import InventoryItem


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'address', 'contact_number', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
   
        fields = ['customer', 'inventory_item', 'quantity', 'price_per_gallon', 'payment_status', 'payment_method']


class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ['name', 'unit', 'stock_in', 'stock_out']



class RestockForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, label="Quantity to Add")
    note = forms.CharField(widget=forms.Textarea, required=False, label="Note (optional)")
