"""Deterministic fictional dataset and schema-compatible ownership manifest."""
import json
from hashlib import sha256
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import CommandError

from main.models import Customer, InventoryItem, StockLog, Transaction

MARKER = 'waterstation-demo-seed:v1:'
MANIFEST_PREFIX = MARKER + 'manifest:'
CUSTOMER_NAMES = (
    'Walk-In Guest A', 'Walk-In Guest B', 'Dalisay Household', 'Malinaw Household',
    'Mabuhay Household', 'Liwanag Household', 'Sample Sunrise Office', 'Sample Bayan Office',
    'Sample Tindahan Sari-Sari', 'Sample Kanto Sari-Sari', 'Sample Kusina Eatery', 'Sample Silog Kitchen',
)
ITEMS = (
    ('[DEMO v1] Purified Water Refill', Decimal('25.00')),
    ('[DEMO v1] Mineral Water Refill', Decimal('35.00')),
    ('[DEMO v1] Alkaline Water Refill', Decimal('45.00')),
)
MANILA = ZoneInfo('Asia/Manila')


def sales_plan():
    result = []
    for index in range(40):
        unpaid = index % 5 == 4
        result.append({
            'customer_index': index % len(CUSTOMER_NAMES),
            'item_index': index % len(ITEMS),
            'quantity': index % 4 + 1,
            'price_per_gallon': ITEMS[index % len(ITEMS)][1],
            'delivery_type': 'delivery' if unpaid or index % 2 else 'walk-in',
            'payment_status': 'unpaid' if unpaid else 'paid',
            'payment_method': ('cash', 'online', 'check')[index % 3],
            'collected_at_end_of_day': False,
            'created_at': datetime.combine(date(2026, 10, 12) + timedelta(days=index // 10), time(8 + index % 10, 15), MANILA),
        })
    return result


def snapshot():
    """Capture only this isolated database's demo business records; no real DB reads."""
    data = {}
    for label, model in (('customers', Customer), ('inventory', InventoryItem), ('transactions', Transaction), ('stock_logs', StockLog)):
        rows = list(model.objects.order_by('pk').values())
        # Normalize the administrative marker stored on the initial stock log.
        if label == 'stock_logs':
            for row in rows:
                if (row['note'] or '').startswith(MANIFEST_PREFIX):
                    row['note'] = MANIFEST_PREFIX
        data[label] = rows
    return json.loads(json.dumps(data, default=str, sort_keys=True))


def fingerprint(records):
    return sha256(json.dumps(records, sort_keys=True).encode('utf-8')).hexdigest()


def inspect_seed_state():
    manifests = list(StockLog.objects.filter(note__startswith=MANIFEST_PREFIX))
    if manifests:
        if len(manifests) != 1:
            raise CommandError('Multiple demo manifests found; refusing changes.')
        try:
            manifest = json.loads(manifests[0].note[len(MANIFEST_PREFIX):])
        except (ValueError, TypeError) as error:
            raise CommandError('Invalid demo ownership manifest; refusing changes.') from error
        counts = {'customers': 12, 'inventory': 3, 'transactions': 40, 'stock_logs': 3}
        records = snapshot()
        if not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('sha256') != fingerprint(records):
            raise CommandError('Demo records were changed or unrecognized records exist; refusing to mix or overwrite data.')
        if manifest.get('counts') != counts or any(len(records[label]) != count for label, count in counts.items()):
            raise CommandError('Incomplete demo dataset; refusing changes.')
        return True
    if any(model.objects.exists() for model in (Customer, InventoryItem, Transaction, StockLog)):
        raise CommandError('Unrecognized business records exist. Seeding requires an empty isolated demo database; nothing was changed.')
    return False


def create_seed():
    customers = []
    for index, name in enumerate(CUSTOMER_NAMES):
        customers.append(Customer.objects.create(
            name='[DEMO v1] ' + name,
            address=f'Fictional Unit {index + 1}, Sample Street, Demo Barangay, Philippines (not a real address)',
            contact_number='NOT A REAL NUMBER',
            notes='Fictional sample customer for client demonstrations only.',
        ))
    items = []
    manifest_log = None
    for name, _ in ITEMS:
        item = InventoryItem.objects.create(name=name, unit='gallons', stock_in=250, stock_out=0)
        log = StockLog.objects.create(inventory_item=item, change=250, note=MANIFEST_PREFIX if manifest_log is None else MARKER + 'initial stock')
        if manifest_log is None:
            manifest_log = log
        items.append(item)
    for row in sales_plan():
        values = row.copy()
        customer = customers[values.pop('customer_index')]
        item = items[values.pop('item_index')]
        historical_date = values.pop('created_at')
        sale = Transaction(customer=customer, inventory_item=item, **values)
        sale.full_clean()
        sale.save()  # The existing atomic model logic deducts stock exactly once.
        # Timestamp-only update AFTER normal creation; never update quantity or stock here.
        Transaction.objects.filter(pk=sale.pk).update(created_at=historical_date)
    records = snapshot()
    manifest = json.dumps({'version': 1, 'counts': {label: len(rows) for label, rows in records.items()}, 'sha256': fingerprint(records)}, sort_keys=True)
    manifest_log.note = MANIFEST_PREFIX + manifest
    manifest_log.save(update_fields=['note'])


def planned_summary():
    rows = sales_plan()
    lines = ['Dataset: 12 fictional customers, 3 gallon inventory items, 40 sales, 3 initial stock logs.',
             'Sales dates: October 12–15, 2026 (Asia/Manila); 10 transactions per date.']
    for label, selected in (('All dates', rows), ('October 14, 2026', [row for row in rows if row['created_at'].date() == date(2026, 10, 14)])):
        total = sum((row['quantity'] * row['price_per_gallon'] for row in selected), Decimal('0.00'))
        unpaid = sum((row['quantity'] * row['price_per_gallon'] for row in selected if row['payment_status'] == 'unpaid'), Decimal('0.00'))
        methods = {method: sum((row['quantity'] * row['price_per_gallon'] for row in selected if row['payment_status'] == 'paid' and row['payment_method'] == method), Decimal('0.00')) for method in ('cash', 'check', 'online')}
        lines.append(f'{label}: {len(selected)} transactions; {sum(row["quantity"] for row in selected)} gallons; sales PHP {total:.2f}; paid PHP {total - unpaid:.2f}; unpaid PHP {unpaid:.2f}; paid cash/check/online PHP {methods["cash"]:.2f}/{methods["check"]:.2f}/{methods["online"]:.2f}.')
    for index, (name, _) in enumerate(ITEMS):
        sold = sum(row['quantity'] for row in rows if row['item_index'] == index)
        lines.append(f'{name}: stock in 250, stock out {sold}, remaining {250 - sold} gallons.')
    return lines
