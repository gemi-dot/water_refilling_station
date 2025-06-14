
# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from .models import Customer
from .forms import CustomerForm

from .models import Transaction
from .forms import TransactionForm


from .models import InventoryItem
from .forms import InventoryItemForm  # You'll create this next



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

