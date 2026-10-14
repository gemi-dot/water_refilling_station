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
    quantity = forms.IntegerField(min_value=1)
    price_per_gallon = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2)

    class Meta:
        model = Transaction
        fields = [
            'customer',
            'inventory_item',
            'quantity',
            'price_per_gallon',
            'delivery_type',
            'payment_status',
            'payment_method',
            'collected_at_end_of_day',
        ]
        widgets = {
            'delivery_type': forms.Select(attrs={'class': 'form-control'}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'collected_at_end_of_day': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }



class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ['name', 'unit', 'stock_in', 'stock_out']



class RestockForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, label="Quantity to Add")
    note = forms.CharField(widget=forms.Textarea, required=False, label="Note (optional)")


class InventoryMetadataForm(forms.ModelForm):
    """Preserve cumulative counts; additions belong in the logged Restock flow."""
    class Meta:
        model = InventoryItem
        fields = ['name', 'unit']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        if self.is_bound:
            for field in ('stock_in', 'stock_out'):
                if field not in self.data:
                    continue
                try:
                    supplied = int(self.data[field])
                except (ValueError, TypeError):
                    raise forms.ValidationError('Stock counts must be valid nonnegative integers.')
                if supplied != getattr(self.instance, field):
                    if field == 'stock_out' and supplied < self.instance.stock_out and self.instance.transaction_set.exists():
                        raise forms.ValidationError('Stock out cannot be less than the quantity in recorded sales. Cumulative counts cannot be edited here.')
                    raise forms.ValidationError('Cumulative stock counts cannot be edited here. Use Restock for recorded stock additions.')
        if 'unit' in cleaned and cleaned['unit'] != self.instance.unit and (self.instance.transaction_set.exists() or self.instance.stocklog_set.exists()):
            self.add_error('unit', 'The unit cannot be changed while sales or stock movement history reference this item.')
        return cleaned
