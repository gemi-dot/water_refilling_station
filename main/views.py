
# Create your views here.
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import QueryDict
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

from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.db.models.deletion import ProtectedError
from .forms import InventoryMetadataForm, SalesFilterForm
from .inventory import LOW_STOCK_THRESHOLD, deletion_reason, inventory_staff_required, stock_movements, stock_status


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
    low_stock_threshold = LOW_STOCK_THRESHOLD
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
    form = SalesFilterForm(request.GET)
    transactions = Transaction.objects.all()
    filter_values = {}
    if form.is_valid():
        filters = form.cleaned_data
        query = filters['q']
        if query:
            search = Q(customer__name__icontains=query) | Q(inventory_item__name__icontains=query)
            number = query[1:] if query.startswith('#') else query
            if number.isascii() and number.isdecimal() and len(number) <= 19 and 0 < int(number) <= 9223372036854775807:
                search |= Q(pk=int(number))
            transactions = transactions.filter(search)
        if filters['start_date']:
            transactions = transactions.filter(created_at__date__gte=filters['start_date'])
        if filters['end_date']:
            transactions = transactions.filter(created_at__date__lte=filters['end_date'])
        if filters['customer']:
            transactions = transactions.filter(customer=filters['customer'])
        if filters['payment_status']:
            transactions = transactions.filter(payment_status=filters['payment_status'])
        if filters['delivery_type']:
            transactions = transactions.filter(delivery_type=filters['delivery_type'])
        for name, value in filters.items():
            if value:
                if name in ('start_date', 'end_date'):
                    value = value.isoformat()
                elif name == 'customer':
                    value = value.pk
                filter_values[name] = str(value)
    else:
        # Do not silently drop invalid filters and show a wider set of sales.
        transactions = transactions.none()
        filter_values = {name: request.GET.get(name, '') for name in form.fields if request.GET.get(name)}

    zero = Decimal('0.00')
    summary = transactions.aggregate(
        transaction_count=Count('pk'),
        total_qty=Sum('quantity', default=0),
        total_revenue=Sum('total_amount', default=zero),
        paid_sales=Sum('total_amount', filter=Q(payment_status='paid'), default=zero),
        unpaid_sales=Sum('total_amount', filter=Q(payment_status='unpaid'), default=zero),
    )
    transactions = transactions.select_related('customer', 'inventory_item').order_by('-created_at', '-pk')
    paginator = Paginator(transactions, 10)
    # Reuse the full filtered aggregate count instead of issuing another COUNT.
    paginator.count = summary['transaction_count']
    page = paginator.get_page(request.GET.get('page'))
    preserved = QueryDict(mutable=True)
    preserved.update(filter_values)
    return render(request, 'main/transactions_list.html', {
        **summary,
        'filter_form': form,
        'transactions': page,
        'start_date': filter_values.get('start_date', ''),
        'end_date': filter_values.get('end_date', ''),
        'filter_query': preserved.urlencode(),
        'page_range': paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        'summary_cards': [
            ('Filtered Transactions', summary['transaction_count'], False),
            ('Filtered Gallons Sold', summary['total_qty'], False),
            ('Filtered Total Sales', summary['total_revenue'], True),
            ('Filtered Paid Sales', summary['paid_sales'], True),
            ('Filtered Unpaid Sales', summary['unpaid_sales'], True),
        ],
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
    inventory_items = list(InventoryItem.objects.annotate(
        has_sales=Exists(Transaction.objects.filter(inventory_item_id=OuterRef('pk'))),
        has_stock_logs=Exists(StockLog.objects.filter(inventory_item_id=OuterRef('pk'))),
    ).order_by('name', 'pk'))
    for item in inventory_items:
        item.stock_status = stock_status(item)
        if item.current_stock() <= LOW_STOCK_THRESHOLD:
            messages.warning(request, f"Low stock alert: {item.name} has only {item.current_stock()} units left. Unit: {item.unit}.")
    return render(request, 'main/inventory_list.html', {
        'inventory_items': inventory_items,
        'low_stock_threshold': LOW_STOCK_THRESHOLD,
        'low_stock_items': sum(item.current_stock() <= LOW_STOCK_THRESHOLD for item in inventory_items),
    })

##########

@inventory_staff_required('add')
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
@inventory_staff_required('change')
@db_transaction.atomic
def inventory_edit(request, pk):
    item = get_object_or_404(InventoryItem.objects.select_for_update(), pk=pk)
    if request.method == 'POST':
        form = InventoryMetadataForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect('inventory_list')
    else:
        form = InventoryMetadataForm(instance=item)
    return render(request, 'main/inventory_edit.html', {'form': form})

# Delete Inventory Item
@inventory_staff_required('delete')
@db_transaction.atomic
def inventory_delete(request, pk):
    item = get_object_or_404(InventoryItem.objects.select_for_update(), pk=pk)
    reason = deletion_reason(item)
    if request.method == 'POST' and not reason:
        try:
            with db_transaction.atomic():
                item.delete()
        except ProtectedError as error:
            reason = str(error.args[0])
        else:
            messages.success(request, 'Inventory item deleted.')
            return redirect('inventory_list')
    return render(request, 'main/inventory_confirm_delete.html', {'item': item, 'deletion_reason': reason})

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

@inventory_staff_required('change')
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
    stock_logs = StockLog.objects.filter(inventory_item=item).order_by('-date', '-pk')
    transactions = Transaction.objects.filter(inventory_item=item).select_related('customer').order_by('-created_at', '-pk')

    context = {
        'item': item,
        'stock_logs': stock_logs,
        'transactions': transactions,
        'movements': stock_movements(stock_logs, transactions),
        'stock_status': stock_status(item),
        'low_stock_threshold': LOW_STOCK_THRESHOLD,
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
