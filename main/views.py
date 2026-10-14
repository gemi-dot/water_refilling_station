
# Create your views here.
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
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

from django.core.paginator import Paginator

from django.db.models import Sum, Count, Q


def dashboard(request):
    today = timezone.localdate()
    dated_today = Q(created_at__date=today)
    zero = Decimal('0.00')
    # Match Daily Report V2: date sales locally and use current payment status.
    summary = Transaction.objects.aggregate(
        total_revenue=Sum('total_amount', default=zero),
        total_transactions=Count('pk'),
        today_sales=Sum('total_amount', filter=dated_today, default=zero),
        today_gallons=Sum('quantity', filter=dated_today, default=0),
        today_paid=Sum('total_amount', filter=dated_today & Q(payment_status='paid'), default=zero),
        today_unpaid=Sum('total_amount', filter=dated_today & Q(payment_status='unpaid'), default=zero),
        today_transactions=Count('pk', filter=dated_today),
    )
    inventory_items = list(InventoryItem.objects.order_by('name', 'pk'))
    # Display-only threshold matches the existing inventory list's 10-unit alert.
    low_stock_threshold = 10
    context = {
        **summary,
        'today': today,
        'total_customers': Customer.objects.count(),
        'inventory_items': inventory_items,
        'low_stock_threshold': low_stock_threshold,
        'low_stock_items': sum(item.current_stock() <= low_stock_threshold for item in inventory_items),
        'recent_transactions': Transaction.objects.select_related('customer', 'inventory_item').order_by('-created_at', '-pk')[:10],
    }
    return render(request, 'main/dashboard.html', context)




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

from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from .models import Transaction

def transactions_list(request):
    transactions = Transaction.objects.all().order_by('-created_at')  # Latest first

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Apply filters based on provided dates
    if start_date and end_date:
        transactions = transactions.filter(created_at__date__range=[start_date, end_date])
    elif start_date:
        transactions = transactions.filter(created_at__date__gte=start_date)
    elif end_date:
        transactions = transactions.filter(created_at__date__lte=end_date)

    paginator = Paginator(transactions, 10)  # Show 10 per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'main/transactions_list.html', {
        'transactions': page_obj,
        'start_date': start_date,
        'end_date': end_date
    })



def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            try:
                form.save()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('transactions_list')
    else:
        form = TransactionForm()
    return render(request, 'main/add_transactions.html', {'form': form})

def edit_transaction(request, pk):
    
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            try:
                form.save()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('transactions_list')
    else:
        form = TransactionForm(instance=transaction)
    return render(request, 'main/edit_transaction.html', {'form': form})  # Correct template name

def transaction_detail(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    return render(request, 'main/transaction_detail.html', {'transaction': transaction})


def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        try:
            transaction.delete()
        except ValidationError as error:
            return render(request, 'main/delete_transaction.html', {
                'transaction': transaction, 'error': error.messages,
            })
        return redirect('transactions_list')
    return render(request, 'main/delete_transaction.html', {'transaction': transaction})

#########

#def home(request):
#    return render(request, 'main/home.html')  # create this template or use any simple response

def home(request):
    return render(request, 'main/home.html', {'transactions_url': 'transactions_list'})



#def inventory_list(request):
#    items = InventoryItem.objects.all()
#    return render(request, 'main/inventory_list.html', {'items': items})

from django.contrib import messages

def inventory_list(request):
    # Fetch all inventory items
    inventory_items = InventoryItem.objects.all()

    # Check for low stock items
    low_stock_items = InventoryItem.objects.annotate(remaining=F('stock_in') - F('stock_out')).filter(remaining__lte=10)  # Threshold set to 10 units
    for item in low_stock_items:
        messages.warning(request, f"Low stock alert: {item.name} has only {item.current_stock()} units left.")

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
@db_transaction.atomic
def inventory_edit(request, pk):
    item = get_object_or_404(InventoryItem.objects.select_for_update(), pk=pk)
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



def daily_report(request):
    selected_date = timezone.localdate()
    date_error = None
    requested_date = request.GET.get('date')
    if requested_date:
        try:
            parsed_date = parse_date(requested_date)
        except ValueError:
            parsed_date = None
        if parsed_date is None or parsed_date.isoformat() != requested_date:
            date_error = 'Please select a valid date in YYYY-MM-DD format. Showing today instead.'
        else:
            selected_date = parsed_date

    delivery_type = request.GET.get('delivery_type', '')
    if delivery_type not in dict(Transaction.DELIVERY_CHOICES):
        delivery_type = ''

    transactions = Transaction.objects.filter(created_at__date=selected_date)
    if delivery_type:
        transactions = transactions.filter(delivery_type=delivery_type)

    zero = Decimal('0.00')
    summary = transactions.aggregate(
        transaction_count=Count('pk'),
        total_qty=Sum('quantity', default=0),
        total_revenue=Sum('total_amount', default=zero),
        paid_sales=Sum('total_amount', filter=Q(payment_status='paid'), default=zero),
        unpaid_sales=Sum('total_amount', filter=Q(payment_status='unpaid'), default=zero),
        cash_sales=Sum('total_amount', filter=Q(payment_status='paid', payment_method='cash'), default=zero),
        check_sales=Sum('total_amount', filter=Q(payment_status='paid', payment_method='check'), default=zero),
        online_sales=Sum('total_amount', filter=Q(payment_status='paid', payment_method='online'), default=zero),
    )
    context = {
        **summary,
        'transactions': transactions.select_related('customer', 'inventory_item').order_by('created_at', 'pk'),
        'date': selected_date.isoformat(),
        'report_date': selected_date,
        'delivery_type': delivery_type,
        'delivery_label': dict(Transaction.DELIVERY_CHOICES).get(delivery_type, 'All'),
        'date_error': date_error,
        'summary_cards': [
            ('Total Transactions', summary['transaction_count'], False),
            ('Gallons Sold', summary['total_qty'], False),
            ('Total Sales', summary['total_revenue'], True),
            ('Paid Sales', summary['paid_sales'], True),
            ('Unpaid Sales', summary['unpaid_sales'], True),
        ],
        'payment_breakdown': [
            ('Cash', summary['cash_sales']),
            ('Check', summary['check_sales']),
            ('Online', summary['online_sales']),
        ],
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

@db_transaction.atomic
def restock_item(request, item_id):
    item = get_object_or_404(InventoryItem.objects.select_for_update(), id=item_id)

    if request.method == 'POST':
        form = RestockForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data['quantity']
            note = form.cleaned_data.get('note', '')

            InventoryItem.objects.filter(pk=item.pk).update(stock_in=F('stock_in') + quantity)

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




def unpaid_delivery_report(request):
    unpaid_deliveries = Transaction.objects.filter(delivery_type='delivery', payment_status='unpaid').order_by('-created_at')

    total_pending_amount = sum(t.total_amount for t in unpaid_deliveries)

    context = {
        'unpaid_deliveries': unpaid_deliveries,
        'total_pending_amount': total_pending_amount,
    }
    return render(request, 'main/unpaid_delivery_report.html', context)