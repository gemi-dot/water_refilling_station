


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


def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('transaction_list')  # You will create this list view next
    else:
        form = TransactionForm()
    return render(request, 'main/add_transactions.html', {'form': form})

# main/views.py
def transaction_list(request):
    transactions = Transaction.objects.all()
    return render(request, 'main/transactions_list.html', {'transactions': transactions})


# main/views.py
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect('transaction_list')
    else:
        form = TransactionForm(instance=transaction)
    return render(request, 'main/edit_transaction.html', {'form': form})

# main/views.py

def transaction_detail(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    return render(request, 'main/transaction_detail.html', {'transaction': transaction})


def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        transaction.delete()
        return redirect('transaction_list')
    return render(request, 'main/delete_transaction.html', {'transaction': transaction})


def home(request):
    return render(request, 'main/home.html')  # create this template or use any simple response



#def inventory_list(request):
#    items = InventoryItem.objects.all()
#    return render(request, 'main/inventory_list.html', {'items': items})

def inventory_list(request):
    inventory_items = InventoryItem.objects.all()
    return render(request, 'main/inventory_list.html', {'inventory_items': inventory_items})




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

