
# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from .models import Customer
from .forms import CustomerForm

from .models import Transaction
from .forms import TransactionForm

from .models import InventoryItem
from .forms import InventoryItemForm  # You'll create this next
from django.utils import timezone
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncMonth


from django.contrib import messages
from django.shortcuts import redirect
from .forms import RestockForm
from .models import InventoryItem, StockLog

from django.utils.dateparse import parse_date




def customer_list(request):
    query = request.GET.get('q', '')
    customers = Customer.objects.all()

    if query:
        customers = customers.filter(name__icontains=query)

    context = {
        'customers': customers,
        'query': query
    }
    return render(request, 'main/customer_list.html', context)
  

def customer_add(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm()
    return render(request, 'main/customer_form.html', {'form': form, 'title': 'Add Customer'})


def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'main/customer_form.html', {'form': form, 'title': 'Edit Customer'})


def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        customer.delete()
        return redirect('customer_list')
    return render(request, 'main/customer_confirm_delete.html', {'customer': customer})

#######start update here

# ... (existing customer views unchanged)

def transaction_list(request):
    transactions = Transaction.objects.select_related('customer', 'inventory_item').all()
    return render(request, 'main/transactions_list.html', {'transactions': transactions})


def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)

            # Convert quantity safely to integer
            quantity = int(transaction.quantity)
            inventory_item = transaction.inventory_item

            # Optional: prevent overselling
            if inventory_item.stock_out + quantity > inventory_item.stock_in:
                form.add_error(None, "Not enough stock available in inventory.")
                return render(request, 'main/add_transactions.html', {'form': form})

            # Save transaction and update inventory
            #transaction.save()
            inventory_item.stock_out += quantity
            inventory_item.save()

            transaction.save()  # Save last


            return redirect('transaction_list')
    else:
        form = TransactionForm()
    return render(request, 'main/add_transactions.html', {'form': form})


def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    original_quantity = int(transaction.quantity)
    original_item = transaction.inventory_item

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            updated_transaction = form.save(commit=False)
            new_quantity = int(updated_transaction.quantity)
            new_item = updated_transaction.inventory_item

            # Revert old stock_out
            original_item.stock_out -= original_quantity
            original_item.save()

            # Optional: prevent overselling new item
            if new_item.stock_out + new_quantity > new_item.stock_in:
                form.add_error(None, "Not enough stock available in selected inventory.")
                # Restore previous stock_out
                original_item.stock_out += original_quantity
                original_item.save()
                return render(request, 'main/edit_transaction.html', {'form': form})

            # Save updated transaction and update new inventory
            updated_transaction.save()
            new_item.stock_out += new_quantity
            new_item.save()

            return redirect('transaction_list')
    else:
        form = TransactionForm(instance=transaction)
    return render(request, 'main/edit_transaction.html', {'form': form})


def transaction_detail(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    return render(request, 'main/transaction_detail.html', {'transaction': transaction})


def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        # Rollback stock_out
        inventory_item = transaction.inventory_item
        inventory_item.stock_out -= int(transaction.quantity)
        inventory_item.save()

        transaction.delete()
        return redirect('transaction_list')
    return render(request, 'main/delete_transaction.html', {'transaction': transaction})

#########

def home(request):
    return render(request, 'main/home.html')  # create this template or use any simple response



#def inventory_list(request):
#    items = InventoryItem.objects.all()
#    return render(request, 'main/inventory_list.html', {'items': items})

def inventory_list(request):
    inventory_items = InventoryItem.objects.all()
    return render(request, 'main/inventory_list.html', {'inventory_items': inventory_items})


##########

def inventory_add(request):
    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('inventory_list')
    else:
        form = InventoryItemForm()
    return render(request, 'main/inventory_add.html', {'form': form})


# Edit Inventory Item
def inventory_edit(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect('inventory_list')
    else:
        form = InventoryItemForm(instance=item)
    return render(request, 'main/inventory_edit.html', {'form': form})

# Delete Inventory Item
def inventory_delete(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        item.delete()
        return redirect('inventory_list')
    return render(request, 'main/inventory_confirm_delete.html', {'item': item})

############
#june14--

##########
from django.shortcuts import render
from django.utils.dateparse import parse_date
from .models import Transaction

def daily_report(request):
    date = request.GET.get('date')  # Get the date from the query parameter
    if date:
        date = parse_date(date)  # Parse the date string into a date object
        transactions = Transaction.objects.filter(created_at__date=date)  # Use created_at__date for filtering
    else:
        transactions = Transaction.objects.all()  # Default to all transactions

    total_qty = sum(t.quantity for t in transactions)
    total_revenue = sum(t.total_amount for t in transactions)

    context = {
        'transactions': transactions,
        'date': date,
        'total_qty': total_qty,
        'total_revenue': total_revenue,
    }
    return render(request, 'main/daily_report.html', context)







#####

def monthly_report(request):
    monthly_data = (
        Transaction.objects
        .annotate(
            month=TruncMonth('created_at'),
            amount=ExpressionWrapper(F('quantity') * F('price_per_gallon'), output_field=DecimalField())
        )
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    return render(request, 'main/monthly_report.html', {'monthly_data': monthly_data})


######

def restock_item(request, item_id):
    item = get_object_or_404(InventoryItem, id=item_id)

    if request.method == 'POST':
        form = RestockForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data['quantity']
            note = form.cleaned_data.get('note', '')

            item.stock_in += quantity
            item.save()

            StockLog.objects.create(
                inventory_item=item,
                change=quantity,
                note=note
            )

            messages.success(request, f"{quantity} units added to {item.name}.")
            return redirect('inventory_item_detail', item_id=item.id)
    else:
        form = RestockForm()

    return render(request, 'main/restock_item.html', {'form': form, 'item': item})

##################


###########

def inventory_item_detail(request, item_id):
    item = get_object_or_404(InventoryItem, pk=item_id)
    stock_logs = StockLog.objects.filter(inventory_item=item).order_by('-date')
    transactions = Transaction.objects.filter(inventory_item=item).order_by('-created_at')

    context = {
        'item': item,
        'stock_logs': stock_logs,
        'transactions': transactions,
    }
    return render(request, 'main/inventory_item_detail.html', context)



