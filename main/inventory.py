"""Read-only inventory presentation rules and server-side staff authorization."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy

LOW_STOCK_THRESHOLD = 10
SALES_DELETE_MESSAGE = 'This inventory item cannot be deleted because it is referenced by existing sales transactions.'
HISTORY_DELETE_MESSAGE = 'This inventory item cannot be deleted because it has recorded stock movement history.'


def stock_status(item):
    remaining = item.current_stock()
    if remaining <= 0:
        return 'Out of Stock'
    if remaining <= LOW_STOCK_THRESHOLD:
        return 'Low Stock'
    return 'In Stock'


def inventory_permission(user, action):
    return user.is_authenticated and user.is_active and user.is_staff and user.has_perm(f'main.{action}_inventoryitem')


def inventory_staff_required(action):
    def decorate(view):
        @login_required(login_url=reverse_lazy('admin:login'))
        @wraps(view)
        def protected(request, *args, **kwargs):
            if not inventory_permission(request.user, action):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return protected
    return decorate


def deletion_reason(item):
    if item.transaction_set.exists():
        return SALES_DELETE_MESSAGE
    if item.stocklog_set.exists():
        return HISTORY_DELETE_MESSAGE
    return None


def stock_movements(stock_logs, sales):
    """Combine stored logs with current sale records; this is not an audit ledger."""
    rows = [
        {'date': log.date, 'type': 'Stock In' if log.change > 0 else 'Adjustment',
         'quantity': log.change, 'source': f'Stock log #{log.pk}', 'note': log.note or '',
         'transaction': None, 'record_kind': 'Recorded stock log', 'pk': log.pk}
        for log in stock_logs
    ]
    rows.extend(
        {'date': sale.created_at, 'type': 'Sale / Stock Out', 'quantity': -sale.quantity,
         'source': f'Sale #{sale.pk} · {sale.customer.name}',
         'note': 'Current sale record, shown at its original sale date; subsequent edits are not separately recorded.',
         'transaction': sale, 'record_kind': 'Reconstructed from current sale', 'pk': sale.pk}
        for sale in sales
    )
    return sorted(rows, key=lambda row: (row['date'], row['record_kind'], row['pk']), reverse=True)
