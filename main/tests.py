from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .forms import InventoryItemForm, TransactionForm
from .models import Customer, InventoryItem, StockLog, Transaction


class InventoryTransactionTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Customer', address='Manila', contact_number='123')
        self.item = InventoryItem.objects.create(name='Water', unit='gallons', stock_in=20)
        self.other = InventoryItem.objects.create(name='Bottled water', unit='pcs', stock_in=10)

    def authorize_inventory(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        staff = get_user_model().objects.create_user(username='inventory-test-staff', is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(codename__in=['add_inventoryitem', 'change_inventoryitem', 'delete_inventoryitem']))
        self.client.force_login(staff)

    def data(self, quantity=5, item=None, **changes):
        data = {
            'customer': self.customer.pk, 'inventory_item': (item or self.item).pk,
            'quantity': quantity, 'price_per_gallon': '25.00',
            'delivery_type': 'walk-in', 'payment_status': 'paid', 'payment_method': 'cash',
        }
        data.update(changes)
        return data

    def sale(self, quantity=5, item=None):
        return Transaction.objects.create(
            customer=self.customer, inventory_item=item or self.item,
            quantity=quantity, price_per_gallon=Decimal('25.00'),
        )

    def balances(self, expected, other=0):
        self.item.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.item.stock_out, expected)
        self.assertEqual(self.other.stock_out, other)
        self.assertGreaterEqual(self.item.current_stock(), 0)
        self.assertGreaterEqual(self.other.current_stock(), 0)

    def test_create_sale_updates_stock_and_total(self):
        response = self.client.post(reverse('add_transaction'), self.data())
        self.assertRedirects(response, reverse('transactions_list'))
        self.balances(5)
        self.assertEqual(Transaction.objects.get().total_amount, Decimal('125.00'))
        self.assertEqual(Customer.objects.count(), 1)

    def test_exact_remaining_stock_can_be_sold(self):
        self.sale(5)
        self.client.post(reverse('add_transaction'), self.data(15))
        self.balances(20)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_overselling_is_rejected_with_visible_error(self):
        self.sale(15)
        response = self.client.post(reverse('add_transaction'), self.data(6))
        self.assertContains(response, 'Not enough stock available')
        self.balances(15)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_invalid_sale_values_do_not_change_inventory(self):
        for values in ({'quantity': 0}, {'quantity': -1}, {'price_per_gallon': '-1.00'}, {'customer': 9999}):
            with self.subTest(values=values):
                response = self.client.post(reverse('add_transaction'), self.data(**values))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.balances(0)
        self.assertFalse(Transaction.objects.exists())

    def test_edit_quantity_increase_decrease_and_unchanged(self):
        sale = self.sale()
        for quantity in (20, 3, 3):
            with self.subTest(quantity=quantity):
                response = self.client.post(reverse('edit_transaction', args=[sale.pk]), self.data(quantity))
                self.assertEqual(response.status_code, 302)
                self.balances(quantity)
                sale.refresh_from_db()
                self.assertEqual(sale.quantity, quantity)
                self.assertEqual(sale.total_amount, quantity * Decimal('25.00'))

    def test_switch_inventory_item_restores_old_stock(self):
        sale = self.sale()
        response = self.client.post(reverse('edit_transaction', args=[sale.pk]), self.data(7, self.other))
        self.assertEqual(response.status_code, 302)
        self.balances(0, 7)
        sale.refresh_from_db()
        self.assertEqual(sale.inventory_item_id, self.other.pk)

    def test_failed_edit_keeps_sale_and_both_balances(self):
        sale = self.sale()
        for item, quantity in ((self.item, 21), (self.other, 11)):
            with self.subTest(item=item.name):
                response = self.client.post(reverse('edit_transaction', args=[sale.pk]), self.data(quantity, item))
                self.assertContains(response, 'Not enough stock available')
                self.balances(5)
                sale.refresh_from_db()
                self.assertEqual(sale.quantity, 5)
                self.assertEqual(sale.inventory_item_id, self.item.pk)
                self.assertEqual(sale.total_amount, Decimal('125.00'))

    def test_invalid_edit_leaves_stock_unchanged(self):
        sale = self.sale()
        response = self.client.post(reverse('edit_transaction', args=[sale.pk]), self.data(0))
        self.assertTrue(response.context['form'].errors)
        self.balances(5)
        sale.refresh_from_db()
        self.assertEqual(sale.quantity, 5)

    def test_delete_requires_post_and_restores_stock_once(self):
        sale = self.sale()
        url = reverse('delete_transaction', args=[sale.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.balances(5)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.balances(0)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.client.post(url).status_code, 404)
        self.balances(0)

    def test_bulk_sale_delete_restores_inventory(self):
        self.sale(5)
        self.sale(3)
        Transaction.objects.all().delete()
        self.balances(0)

    def test_creation_database_failure_rolls_back_stock(self):
        with patch('django.db.models.Model.save', side_effect=DatabaseError('save failed')):
            with self.assertRaises(DatabaseError):
                self.sale()
        self.balances(0)
        self.assertFalse(Transaction.objects.exists())

    def test_edit_database_failure_rolls_back_both_items(self):
        sale = self.sale()
        sale.inventory_item = self.other
        sale.quantity = 7
        with patch('django.db.models.Model.save', side_effect=DatabaseError('save failed')):
            with self.assertRaises(DatabaseError):
                sale.save()
        self.balances(5)
        sale.refresh_from_db()
        self.assertEqual(sale.inventory_item_id, self.item.pk)
        self.assertEqual(sale.quantity, 5)

    def test_delete_database_failure_rolls_back_stock(self):
        sale = self.sale()
        with patch('django.db.models.sql.subqueries.DeleteQuery.delete_batch', side_effect=DatabaseError('delete failed')):
            with self.assertRaises(DatabaseError):
                sale.delete()
        self.balances(5)
        self.assertTrue(Transaction.objects.filter(pk=sale.pk).exists())

    def test_stale_item_instances_do_not_allow_overselling(self):
        stale = InventoryItem.objects.get(pk=self.item.pk)
        self.sale(18)
        with self.assertRaises(ValidationError):
            self.sale(3, stale)
        self.balances(18)

    def test_stale_sale_edit_uses_stored_original_quantity(self):
        sale = self.sale()
        stale = Transaction.objects.get(pk=sale.pk)
        sale.quantity = 10
        sale.save()
        stale.quantity = 7
        stale.save()
        self.balances(7)

    def test_partial_save_preserves_stock_and_recalculates_total(self):
        sale = self.sale()
        sale.quantity = 100
        sale.payment_status = 'unpaid'
        sale.save(update_fields=['payment_status'])
        self.balances(5)
        sale.refresh_from_db()
        self.assertEqual(sale.quantity, 5)
        self.assertEqual(sale.payment_status, 'unpaid')
        self.assertEqual(sale.total_amount, Decimal('125.00'))

    def test_low_stock_uses_remaining_stock_in_dashboard_and_alerts(self):
        self.sale(12)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['low_stock_items'], 2)
        self.assertEqual(response.context['total_transactions'], 1)
        self.assertEqual(response.context['total_revenue'], Decimal('300.00'))
        response = self.client.get(reverse('inventory_list'))
        self.assertContains(response, 'Water has only 8 units left.')
        self.assertContains(response, 'Bottled water has only 10 units left.')
        self.assertContains(response, 'table table-bordered table-striped')

    def test_inventory_add_and_edit_reject_negative_balances(self):
        self.authorize_inventory()
        for stock_in, stock_out in ((-1, 0), (10, -1), (5, 6)):
            with self.subTest(stock_in=stock_in, stock_out=stock_out):
                data = {'name': 'Invalid', 'unit': 'pcs', 'stock_in': stock_in, 'stock_out': stock_out}
                self.assertFalse(InventoryItemForm(data).is_valid())
                response = self.client.post(reverse('inventory_add'), data)
                self.assertEqual(response.status_code, 200)
                response = self.client.post(reverse('inventory_edit', args=[self.item.pk]), data)
                self.assertEqual(response.status_code, 200)
                self.balances(0)
        self.assertEqual(InventoryItem.objects.count(), 2)

    def test_inventory_edit_cannot_erase_recorded_sales_stock(self):
        self.authorize_inventory()
        self.sale()
        response = self.client.post(reverse('inventory_edit', args=[self.item.pk]), {
            'name': 'Water', 'unit': 'gallons', 'stock_in': 20, 'stock_out': 0,
        })
        self.assertContains(response, 'Stock out cannot be less')
        self.balances(5)

    def test_restock_adds_inventory_and_log(self):
        self.authorize_inventory()
        self.sale()
        response = self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': 4, 'note': 'Delivery'})
        self.assertEqual(response.status_code, 302)
        self.balances(5)
        self.assertEqual(self.item.stock_in, 24)
        log = StockLog.objects.get()
        self.assertEqual(log.change, 4)
        self.assertEqual(log.note, 'Delivery')

    def test_restock_failure_rolls_back_inventory(self):
        self.authorize_inventory()
        with patch('main.views.StockLog.objects.create', side_effect=DatabaseError('log failed')):
            with self.assertRaises(DatabaseError):
                self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': 4})
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 20)
        self.assertFalse(StockLog.objects.exists())

    def test_invalid_restock_does_not_change_inventory(self):
        self.authorize_inventory()
        for quantity in (0, -1, 'invalid'):
            response = self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': quantity})
            self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 20)
        self.assertFalse(StockLog.objects.exists())


class DailyReportTests(TestCase):
    def setUp(self):
        from datetime import date
        self.report_date = date(2026, 10, 14)
        self.customer = Customer.objects.create(name='Report Customer', address='Manila', contact_number='456')
        self.item = InventoryItem.objects.create(name='Report Water', unit='gallons', stock_in=100)
        self.url = reverse('daily_report')
        self.cash = self.make_sale(2, '10.25', 'paid', 'cash')
        self.check = self.make_sale(3, '20.10', 'paid', 'check', 'delivery')
        self.online = self.make_sale(1, '30.15', 'paid', 'online')
        self.unpaid = self.make_sale(4, '5.05', 'unpaid', 'cash', 'delivery')
        self.previous_day = self.make_sale(1, '99.99', 'paid', 'cash', day_offset=-1)

    def make_sale(self, quantity, price, status, method, delivery='walk-in', day_offset=0):
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo
        sale = Transaction.objects.create(
            customer=self.customer, inventory_item=self.item, quantity=quantity,
            price_per_gallon=Decimal(price), payment_status=status,
            payment_method=method, delivery_type=delivery,
        )
        timestamp = datetime.combine(self.report_date + timedelta(days=day_offset), time(12), ZoneInfo('Asia/Manila'))
        Transaction.objects.filter(pk=sale.pk).update(created_at=timestamp)
        return sale

    def report(self, **filters):
        return self.client.get(self.url, {'date': self.report_date.isoformat(), **filters})

    def test_default_date_uses_local_today(self):
        with patch('main.views.timezone.localdate', return_value=self.report_date):
            response = self.client.get(self.url)
        self.assertEqual(response.context['report_date'], self.report_date)
        self.assertEqual(response.context['date'], '2026-10-14')
        self.assertEqual(response.context['transaction_count'], 4)

    def test_selected_date_excludes_other_dates(self):
        response = self.report()
        self.assertEqual({sale.pk for sale in response.context['transactions']}, {
            self.cash.pk, self.check.pk, self.online.pk, self.unpaid.pk,
        })
        response = self.report(date='2026-10-13')
        self.assertEqual(response.context['transaction_count'], 1)
        self.assertEqual(response.context['total_revenue'], Decimal('99.99'))

    def test_local_midnight_boundaries(self):
        from datetime import datetime, timezone as dt_timezone
        # Manila's Oct 14 begins at Oct 13 16:00 UTC and ends before Oct 14 16:00 UTC.
        timestamps = [
            datetime(2026, 10, 13, 15, 59, 59, tzinfo=dt_timezone.utc),
            datetime(2026, 10, 13, 16, 0, tzinfo=dt_timezone.utc),
            datetime(2026, 10, 14, 15, 59, 59, tzinfo=dt_timezone.utc),
            datetime(2026, 10, 14, 16, 0, tzinfo=dt_timezone.utc),
        ]
        for sale, timestamp in zip((self.cash, self.check, self.online, self.unpaid), timestamps):
            Transaction.objects.filter(pk=sale.pk).update(created_at=timestamp)
        response = self.report()
        self.assertEqual({sale.pk for sale in response.context['transactions']}, {self.check.pk, self.online.pk})

    def test_delivery_filters_apply_to_rows_and_totals(self):
        response = self.report(delivery_type='delivery')
        self.assertEqual(response.context['transaction_count'], 2)
        self.assertEqual(response.context['total_qty'], 7)
        self.assertEqual(response.context['total_revenue'], Decimal('80.50'))
        self.assertEqual(response.context['paid_sales'], Decimal('60.30'))
        self.assertEqual(response.context['unpaid_sales'], Decimal('20.20'))
        self.assertEqual(response.context['cash_sales'], Decimal('0.00'))
        self.assertEqual(response.context['check_sales'], Decimal('60.30'))
        self.assertEqual(response.context['online_sales'], Decimal('0.00'))
        self.assertEqual(response.context['delivery_type'], 'delivery')
        response = self.report(delivery_type='walk-in')
        self.assertEqual(response.context['transaction_count'], 2)
        self.assertEqual(response.context['total_qty'], 3)
        self.assertEqual(response.context['total_revenue'], Decimal('50.65'))

    def test_quantities_and_sales_totals_are_exact(self):
        response = self.report()
        self.assertEqual(response.context['transaction_count'], 4)
        self.assertEqual(response.context['total_qty'], 10)
        self.assertEqual(response.context['total_revenue'], Decimal('131.15'))
        self.assertIsInstance(response.context['total_revenue'], Decimal)

    def test_paid_unpaid_and_method_totals_reconcile(self):
        context = self.report().context
        self.assertEqual(context['paid_sales'], Decimal('110.95'))
        self.assertEqual(context['unpaid_sales'], Decimal('20.20'))
        self.assertEqual(context['cash_sales'], Decimal('20.50'))
        self.assertEqual(context['check_sales'], Decimal('60.30'))
        self.assertEqual(context['online_sales'], Decimal('30.15'))
        self.assertEqual(context['paid_sales'] + context['unpaid_sales'], context['total_revenue'])
        self.assertEqual(sum(context[key] for key in ('cash_sales', 'check_sales', 'online_sales')), context['paid_sales'])

    def test_collection_flag_does_not_filter_paid_sales(self):
        Transaction.objects.filter(pk=self.check.pk).update(collected_at_end_of_day=True)
        self.assertEqual(self.report().context['paid_sales'], Decimal('110.95'))

    def test_invalid_dates_fall_back_to_today_with_warning(self):
        for value in ('not-a-date', '2026-02-30', '2026-13-14', '2026-1-4', '20261014', '0000-01-01'):
            with self.subTest(date=value), patch('main.views.timezone.localdate', return_value=self.report_date):
                response = self.client.get(self.url, {'date': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['report_date'], self.report_date)
                self.assertContains(response, 'Please select a valid date')
                self.assertEqual(response.context['transaction_count'], 4)

    def test_empty_date_defaults_to_today(self):
        with patch('main.views.timezone.localdate', return_value=self.report_date):
            response = self.client.get(self.url, {'date': ''})
        self.assertEqual(response.context['report_date'], self.report_date)
        self.assertIsNone(response.context['date_error'])

    def test_unknown_delivery_filter_defaults_to_all(self):
        response = self.report(delivery_type='unknown')
        self.assertEqual(response.context['delivery_type'], '')
        self.assertEqual(response.context['transaction_count'], 4)

    def test_empty_report_returns_zero_totals_and_friendly_message(self):
        response = self.report(date='2026-10-12')
        for key in ('transaction_count', 'total_qty', 'total_revenue', 'paid_sales', 'unpaid_sales', 'cash_sales', 'check_sales', 'online_sales'):
            with self.subTest(key=key):
                self.assertEqual(response.context[key], 0)
        self.assertIsInstance(response.context['total_revenue'], Decimal)
        self.assertContains(response, 'No transactions found for the selected date')
        self.assertContains(response, '₱0.00')

    def test_rendering_contains_report_details_and_print_controls(self):
        response = self.report()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'main/daily_report.html')
        self.assertTemplateUsed(response, 'main/base.html')
        for text in ('Daily Sales and Collection Summary', 'October 14, 2026', 'Report Customer', 'Report Water', '₱10.25', '₱131.15', 'Paid Sales by Payment Method', 'Payment Method', 'window.print()', '@media print', 'A4 landscape', 'no payment collection timestamp'):
            with self.subTest(text=text):
                self.assertContains(response, text)

    def test_report_does_not_mutate_sales_or_inventory(self):
        before_sales = list(Transaction.objects.order_by('pk').values())
        before_inventory = list(InventoryItem.objects.order_by('pk').values())
        self.report()
        self.assertEqual(list(Transaction.objects.order_by('pk').values()), before_sales)
        self.assertEqual(list(InventoryItem.objects.order_by('pk').values()), before_inventory)

    def test_report_data_uses_two_queries_without_related_lookup_queries(self):
        from django.test import RequestFactory
        from .views import daily_report
        request = RequestFactory().get(self.url, {'date': '2026-10-14'})
        with patch('main.views.render', side_effect=lambda request, template, context: context):
            with self.assertNumQueries(2):
                context = daily_report(request)
                rows = [(sale.customer.name, sale.inventory_item.name) for sale in context['transactions']]
        self.assertEqual(len(rows), 4)


class DemoAdministrativeCommandTests(SimpleTestCase):
    """Run real commands against disposable, file-backed SQLite demo databases only."""
    databases = {'default'}

    def setUp(self):
        import copy
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.db import connections
        from django.db.backends.sqlite3.base import DatabaseWrapper
        from django.test import override_settings
        from django.core.management import call_command

        self.temporary_directory = TemporaryDirectory(prefix='waterstation-demo-test-')
        self.base_dir = Path(self.temporary_directory.name).resolve()
        self.original_connection = connections['default']
        config = copy.deepcopy(self.original_connection.settings_dict)
        config.update(ENGINE='django.db.backends.sqlite3', NAME=self.base_dir / 'db.demo.sqlite3')
        self.demo_connection = DatabaseWrapper(config, alias='default')
        self.settings_override = override_settings(BASE_DIR=self.base_dir, WATERSTATION_DEMO_DB=True)
        self.settings_override.enable()
        connections._connections.default = self.demo_connection
        self.addCleanup(self.cleanup_database)
        call_command('migrate', verbosity=0, interactive=False)

    def cleanup_database(self):
        from django.db import connections
        self.demo_connection.close()
        connections._connections.default = self.original_connection
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def command(self, name='seed_demo_data', **options):
        from io import StringIO
        from django.core.management import call_command
        output = StringIO()
        call_command(name, stdout=output, **options)
        return output.getvalue()

    def test_seed_creates_expected_records_and_correct_totals(self):
        output = self.command()
        self.assertIn('Created: 12 customers', output)
        self.assertEqual(Customer.objects.count(), 12)
        self.assertEqual(InventoryItem.objects.count(), 3)
        self.assertEqual(Transaction.objects.count(), 40)
        self.assertEqual(StockLog.objects.count(), 3)
        for sale in Transaction.objects.all():
            self.assertEqual(sale.total_amount, sale.quantity * sale.price_per_gallon)
            self.assertTrue(sale.customer.name.startswith('[DEMO v1]'))
        self.assertEqual(sum(sale.quantity for sale in Transaction.objects.all()), 100)

    def test_repeated_seed_is_idempotent_without_changes(self):
        from main.management.demo_data import snapshot
        self.command()
        before = snapshot()
        output = self.command()
        self.assertIn('Created: 0 customers', output)
        self.assertEqual(snapshot(), before)

    def test_seed_inventory_and_stock_logs_are_consistent(self):
        from django.db.models import Sum
        self.command()
        for item in InventoryItem.objects.all():
            sold = item.transaction_set.aggregate(total=Sum('quantity'))['total']
            self.assertEqual(item.stock_out, sold)
            self.assertEqual(item.stock_in, 250)
            self.assertEqual(item.current_stock(), 250 - sold)
            self.assertGreaterEqual(item.current_stock(), 0)
            self.assertEqual(item.stocklog_set.get().change, 250)

    def test_seed_dry_run_writes_nothing(self):
        from main.models import DemoSettings
        output = self.command(dry_run=True)
        self.assertIn('DRY RUN', output)
        for model in (Customer, InventoryItem, Transaction, StockLog, DemoSettings):
            self.assertEqual(model.objects.count(), 0)

    def test_failed_seed_rolls_back_every_business_record(self):
        original_save = Transaction.save
        calls = 0

        def failing_save(instance, *args, **kwargs):
            nonlocal calls
            original_save(instance, *args, **kwargs)
            calls += 1
            if calls == 7:
                raise DatabaseError('Injected failure after stock deduction and sale save')

        with patch('main.models.Transaction.save', new=failing_save):
            with self.assertRaises(DatabaseError):
                self.command()
        for model in (Customer, InventoryItem, Transaction, StockLog):
            self.assertEqual(model.objects.count(), 0)

    def test_historical_dates_are_local_and_no_stock_is_deducted_twice(self):
        from django.utils import timezone
        self.command()
        counts = {}
        for sale in Transaction.objects.all():
            self.assertTrue(timezone.is_aware(sale.created_at))
            day = timezone.localdate(sale.created_at).isoformat()
            counts[day] = counts.get(day, 0) + 1
        self.assertEqual(counts, {f'2026-10-{day}': 10 for day in (12, 13, 14, 15)})
        self.assertEqual(sum(item.stock_out for item in InventoryItem.objects.all()), 100)

    def test_seed_data_daily_report_and_accounting_reconcile(self):
        self.command()
        response = self.client.get(reverse('daily_report'), {'date': '2026-10-14'})
        self.assertEqual(response.status_code, 200)
        context = response.context
        self.assertEqual(context['transaction_count'], 10)
        self.assertEqual(context['total_qty'], 23)
        self.assertEqual(context['total_revenue'], Decimal('835.00'))
        self.assertEqual(context['paid_sales'], Decimal('720.00'))
        self.assertEqual(context['unpaid_sales'], Decimal('115.00'))
        self.assertEqual(context['cash_sales'], Decimal('150.00'))
        self.assertEqual(context['check_sales'], Decimal('360.00'))
        self.assertEqual(context['online_sales'], Decimal('210.00'))
        self.assertEqual(context['paid_sales'] + context['unpaid_sales'], context['total_revenue'])
        self.assertEqual(sum(context[key] for key in ('cash_sales', 'check_sales', 'online_sales')), context['paid_sales'])
        for key in ('paid_sales', 'unpaid_sales', 'cash_sales', 'check_sales', 'online_sales'):
            self.assertGreater(context[key], 0)
        self.assertContains(response, '[DEMO v1]')

    def test_unrecognized_customer_is_never_overwritten_or_mixed(self):
        from django.core.management.base import CommandError
        customer = Customer.objects.create(name='Existing record', address='Do not change', contact_number='N/A')
        for command, options in (('seed_demo_data', {}), ('reset_demo_period', {'days': 30, 'confirm': True})):
            with self.subTest(command=command), self.assertRaises(CommandError):
                self.command(command, **options)
        customer.refresh_from_db()
        self.assertEqual(customer.address, 'Do not change')
        self.assertEqual(Customer.objects.count(), 1)
        self.assertFalse(InventoryItem.objects.exists())

    def test_unrecognized_inventory_without_customers_is_rejected(self):
        from django.core.management.base import CommandError
        InventoryItem.objects.create(name='Unmarked stock', unit='gallons', stock_in=10)
        with self.assertRaises(CommandError):
            self.command()
        self.assertFalse(Customer.objects.exists())

    def test_changed_or_extra_demo_records_are_never_repaired_or_overwritten(self):
        from django.core.management.base import CommandError
        from main.management.demo_data import snapshot
        self.command()
        customer = Customer.objects.order_by('pk').last()
        customer.address = 'Edited in demonstration'
        customer.save()
        before = snapshot()
        with self.assertRaises(CommandError):
            self.command()
        self.assertEqual(snapshot(), before)

    def test_invalid_manifest_is_rejected(self):
        from django.core.management.base import CommandError
        from main.management.demo_data import MANIFEST_PREFIX
        item = InventoryItem.objects.create(name='Invalid marker', unit='gallons', stock_in=10)
        StockLog.objects.create(inventory_item=item, change=10, note=MANIFEST_PREFIX + '{broken')
        with self.assertRaises(CommandError):
            self.command()
        self.assertFalse(Transaction.objects.exists())

    def test_both_commands_reject_normal_database_mode(self):
        from django.core.management.base import CommandError
        with self.settings(WATERSTATION_DEMO_DB=False):
            for name, options in (('seed_demo_data', {}), ('reset_demo_period', {'days': 30, 'confirm': True})):
                with self.subTest(command=name), self.assertRaises(CommandError):
                    self.command(name, **options)
        self.assertFalse(Customer.objects.exists())

    def test_guard_rejects_default_path_and_production_backends_before_query(self):
        from django.core.management.base import CommandError
        from main.management.demo_safety import require_demo_database
        for engine, name in (
            ('django.db.backends.sqlite3', self.base_dir / 'db.sqlite3'),
            ('django.db.backends.postgresql', self.base_dir / 'db.demo.sqlite3'),
            ('django.db.backends.mysql', self.base_dir / 'db.demo.sqlite3'),
        ):
            with self.subTest(engine=engine, name=name), patch.dict(self.demo_connection.settings_dict, ENGINE=engine, NAME=name):
                with patch.object(self.demo_connection, 'cursor', side_effect=AssertionError('Unsafe database opened')):
                    with self.assertRaises(CommandError):
                        require_demo_database()

    def test_guard_rejects_mismatched_live_connection(self):
        from django.core.management.base import CommandError
        from main.management.demo_safety import require_demo_database
        normal = self.base_dir / 'db.sqlite3'
        normal.touch()
        with self.settings(BASE_DIR=self.base_dir / 'another'):
            with self.assertRaises(CommandError):
                require_demo_database()
        # Advertise the right pathname while the live connection is a different file.
        with patch.object(self.demo_connection, 'cursor') as cursor:
            cursor.return_value.__enter__.return_value.fetchall.return_value = [(0, 'main', str(normal))]
            with self.assertRaises(CommandError):
                require_demo_database()

    def test_guard_rejects_symlink_and_hardlink_to_normal_database(self):
        import os
        from django.core.management.base import CommandError
        from main.management.demo_safety import require_demo_database
        normal = self.base_dir / 'db.sqlite3'
        normal.touch()
        alias = self.base_dir / 'link'
        alias.symlink_to(normal)
        with patch.dict(self.demo_connection.settings_dict, NAME=alias):
            with self.assertRaises(CommandError):
                require_demo_database()
        linked_dir = self.base_dir / 'linked-demo'
        linked_dir.mkdir()
        designated_symlink = linked_dir / 'db.demo.sqlite3'
        designated_symlink.symlink_to(normal)
        with self.settings(BASE_DIR=linked_dir), patch.dict(self.demo_connection.settings_dict, NAME=designated_symlink):
            with self.assertRaises(CommandError):
                require_demo_database()
        hardlink = self.base_dir / 'hardlinked'
        os.link(self.base_dir / 'db.demo.sqlite3', hardlink)
        with self.assertRaises(CommandError):
            require_demo_database()

    def test_guard_missing_database_does_not_create_file(self):
        from django.core.management.base import CommandError
        from main.management.demo_safety import require_demo_database
        missing_dir = self.base_dir / 'missing'
        missing_dir.mkdir()
        missing_file = missing_dir / 'db.demo.sqlite3'
        with self.settings(BASE_DIR=missing_dir), patch.dict(self.demo_connection.settings_dict, NAME=missing_file):
            with self.assertRaises(CommandError):
                require_demo_database()
        self.assertFalse(missing_file.exists())

    def test_reset_rejects_invalid_durations(self):
        from django.core.management.base import CommandError
        from main.models import DemoSettings
        for days in (-1, 0, 366):
            with self.subTest(days=days), self.assertRaises(CommandError):
                self.command('reset_demo_period', days=days, confirm=True)
        self.assertFalse(DemoSettings.objects.exists())

    def test_reset_requires_explicit_duration_and_confirmation(self):
        from django.core.management.base import CommandError
        from main.models import DemoSettings
        with self.assertRaises(CommandError):
            self.command('reset_demo_period')
        with self.assertRaises(CommandError):
            self.command('reset_demo_period', days=30)
        self.assertFalse(DemoSettings.objects.exists())

    def test_reset_dry_run_preserves_settings_users_and_logs(self):
        from django.contrib.admin.models import LogEntry
        from django.contrib.auth import get_user_model
        from main.models import DemoSettings
        instance = DemoSettings.objects.create(demo_duration_days=7, is_active=False)
        before = list(DemoSettings.objects.values())
        users = get_user_model().objects.count()
        output = self.command('reset_demo_period', days=30, dry_run=True)
        self.assertIn('Current demo configuration:', output)
        self.assertIn('Proposed demo configuration:', output)
        self.assertIn('DRY RUN', output)
        self.assertEqual(list(DemoSettings.objects.values()), before)
        self.assertEqual(get_user_model().objects.count(), users)
        self.assertFalse(LogEntry.objects.exists())

    def test_reset_dry_run_with_no_settings_creates_nothing(self):
        from django.contrib.auth import get_user_model
        from main.models import DemoSettings
        self.command('reset_demo_period', days=30, dry_run=True)
        self.assertFalse(DemoSettings.objects.exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_confirmed_reset_uses_existing_semantics_and_audit(self):
        import json
        from datetime import timedelta
        from django.contrib.admin.models import LogEntry
        from django.utils import timezone
        from main.models import DemoSettings
        now = timezone.now()
        instance = DemoSettings.objects.create(demo_start_date=now - timedelta(days=20), demo_duration_days=7, is_active=False)
        with patch('main.management.commands.reset_demo_period.timezone.now', return_value=now):
            self.command('reset_demo_period', days=30, confirm=True)
        instance.refresh_from_db()
        self.assertEqual(instance.demo_start_date, now)
        self.assertEqual(instance.demo_duration_days, 30)
        self.assertTrue(instance.is_active)
        self.assertFalse(instance.has_expired())
        self.assertEqual(DemoSettings.objects.count(), 1)
        log = LogEntry.objects.get()
        audit = json.loads(log.change_message)
        self.assertEqual(audit['before']['days'], 7)
        self.assertEqual(audit['after']['days'], 30)
        self.assertEqual(audit['operation'], 'reset_demo_period')
        self.assertFalse(log.user.has_usable_password())
        self.assertFalse(log.user.is_active)
        self.assertFalse(log.user.is_staff)

    def test_confirmed_reset_can_initialize_settings_without_changing_superuser(self):
        from django.contrib.auth import get_user_model
        from main.models import DemoSettings
        user = get_user_model().objects.create_superuser(username='demo-admin', password='test-password-only')
        before = user.password
        self.command('reset_demo_period', days=14, confirm=True)
        self.assertEqual(DemoSettings.objects.get().demo_duration_days, 14)
        user.refresh_from_db()
        self.assertEqual(user.password, before)
        self.assertTrue(user.is_superuser)

    def test_audit_failure_rolls_back_settings_and_audit_account(self):
        from django.contrib.auth import get_user_model
        from main.models import DemoSettings
        instance = DemoSettings.objects.create(demo_duration_days=7, is_active=False)
        before = list(DemoSettings.objects.values())
        with patch('main.management.commands.reset_demo_period.LogEntry.objects.create', side_effect=DatabaseError('Audit failure')):
            with self.assertRaises(DatabaseError):
                self.command('reset_demo_period', days=30, confirm=True)
        self.assertEqual(list(DemoSettings.objects.values()), before)
        self.assertFalse(get_user_model().objects.exists())

    def test_reset_audit_account_collision_does_not_change_account_or_settings(self):
        from django.contrib.auth import get_user_model
        from django.core.management.base import CommandError
        from main.management.commands.reset_demo_period import AUDIT_USERNAME
        from main.models import DemoSettings
        user = get_user_model().objects.create_superuser(username=AUDIT_USERNAME, password='test-password-only')
        before = user.password
        with self.assertRaises(CommandError):
            self.command('reset_demo_period', days=30, confirm=True)
        user.refresh_from_db()
        self.assertEqual(user.password, before)
        self.assertTrue(user.is_active)
        self.assertFalse(DemoSettings.objects.exists())

    def test_reset_after_seed_preserves_business_records(self):
        from main.management.demo_data import snapshot
        self.command()
        before = snapshot()
        self.command('reset_demo_period', days=30, confirm=True)
        self.assertEqual(snapshot(), before)
        self.assertIn('Created: 0 customers', self.command())

    def test_settings_select_only_dedicated_sqlite_when_opted_in(self):
        import os
        import runpy
        from pathlib import Path
        from waterstation import settings as project_settings
        for flag, filename in (('0', 'db.sqlite3'), ('1', 'db.demo.sqlite3')):
            with self.subTest(flag=flag), patch.dict(os.environ, WATERSTATION_DEMO_DB=flag):
                configuration = runpy.run_path(project_settings.__file__)
                self.assertEqual(configuration['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
                self.assertEqual(Path(configuration['DATABASES']['default']['NAME']), configuration['BASE_DIR'] / filename)

    def test_guard_rejects_attached_database(self):
        from django.core.management.base import CommandError
        from main.management.demo_safety import require_demo_database
        with self.demo_connection.cursor() as cursor:
            cursor.execute("ATTACH DATABASE ':memory:' AS foreign_data")
        with self.assertRaises(CommandError):
            require_demo_database()


class DashboardV3Tests(TestCase):
    def setUp(self):
        from datetime import date
        from django.contrib.auth import get_user_model
        self.today = date(2026, 10, 14)
        self.user = get_user_model().objects.create_user(username='dashboard-reviewer', password='test-only-password')
        self.customer = Customer.objects.create(name='Dashboard Customer', address='Fictional address', contact_number='N/A')
        self.non_buyer = Customer.objects.create(name='Customer Without Sales', address='Fictional address', contact_number='N/A')
        self.item = InventoryItem.objects.create(name='Purified Refill', unit='gallons', stock_in=100)
        self.paid_sale = self.sale(2, '25.50', 'paid', hour=9)
        self.unpaid_sale = self.sale(3, '30.25', 'unpaid', hour=10)
        self.yesterday_sale = self.sale(4, '40.00', 'paid', day_offset=-1)
        self.url = reverse('dashboard')
        self.client.force_login(self.user)

    def sale(self, quantity, price, status, day_offset=0, hour=12):
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo
        sale = Transaction.objects.create(
            customer=self.customer, inventory_item=self.item, quantity=quantity,
            price_per_gallon=Decimal(price), payment_status=status,
            delivery_type='delivery' if status == 'unpaid' else 'walk-in',
        )
        timestamp = datetime.combine(self.today + timedelta(days=day_offset), time(hour), ZoneInfo('Asia/Manila'))
        Transaction.objects.filter(pk=sale.pk).update(created_at=timestamp)
        return sale

    def dashboard(self):
        with patch('main.views.timezone.localdate', return_value=self.today):
            return self.client.get(self.url)

    def test_authorized_user_sees_dashboard_and_existing_action_links(self):
        response = self.dashboard()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'main/dashboard.html')
        self.assertTemplateUsed(response, 'main/base.html')
        for text in ("Today's Total Sales", 'Gallons Sold Today', 'Paid Sales Today', 'Unpaid Sales Today', 'Total Customers', 'Inventory Overview', 'Recent Transactions', 'Quick Actions', 'October 14, 2026', 'table-responsive'):
            with self.subTest(text=text):
                self.assertContains(response, text)
        for route in ('add_transaction', 'customer_list', 'inventory_list', 'daily_report'):
            self.assertContains(response, reverse(route))

    def test_today_sales_paid_unpaid_and_gallons_match_daily_report(self):
        response = self.dashboard()
        context = response.context
        self.assertEqual(context['today_sales'], Decimal('141.75'))
        self.assertEqual(context['today_paid'], Decimal('51.00'))
        self.assertEqual(context['today_unpaid'], Decimal('90.75'))
        self.assertEqual(context['today_gallons'], 5)
        self.assertEqual(context['today_transactions'], 2)
        self.assertEqual(context['today_paid'] + context['today_unpaid'], context['today_sales'])
        report = self.client.get(reverse('daily_report'), {'date': self.today.isoformat()})
        for dashboard_key, report_key in (('today_sales', 'total_revenue'), ('today_paid', 'paid_sales'), ('today_unpaid', 'unpaid_sales'), ('today_gallons', 'total_qty')):
            self.assertEqual(context[dashboard_key], report.context[report_key])
        self.assertContains(response, '₱141.75')
        self.assertContains(response, 'not cash collected today')

    def test_customer_count_includes_registered_customers_without_sales(self):
        self.assertEqual(self.dashboard().context['total_customers'], 2)

    def test_inventory_remaining_stock_and_status_boundaries(self):
        InventoryItem.objects.create(name='Empty', unit='gallons', stock_in=5, stock_out=5)
        InventoryItem.objects.create(name='Low', unit='gallons', stock_in=20, stock_out=10)
        InventoryItem.objects.create(name='Healthy', unit='pcs', stock_in=11)
        response = self.dashboard()
        self.assertEqual(response.context['low_stock_threshold'], 10)
        self.assertEqual(response.context['low_stock_items'], 2)
        for text in ('91 gallons', '0 gallons', '10 gallons', '11 pcs', 'Out of Stock', 'Low Stock', 'In Stock', '10 units or fewer'):
            with self.subTest(text=text):
                self.assertContains(response, text)

    def test_recent_transactions_are_newest_first_with_deterministic_ties_and_limit(self):
        for index in range(12):
            self.sale(1, '1.00', 'paid', hour=15)
        response = self.dashboard()
        rows = list(response.context['recent_transactions'])
        expected = list(Transaction.objects.order_by('-created_at', '-pk').values_list('pk', flat=True)[:10])
        self.assertEqual([sale.pk for sale in rows], expected)
        self.assertEqual(len(rows), 10)

    def test_recent_transactions_include_previous_days(self):
        rows = list(self.dashboard().context['recent_transactions'])
        self.assertEqual([sale.pk for sale in rows], [self.unpaid_sale.pk, self.paid_sale.pk, self.yesterday_sale.pk])

    def test_local_calendar_day_includes_exact_midnight_boundaries(self):
        from datetime import datetime, timezone as dt_timezone
        Transaction.objects.filter(pk=self.paid_sale.pk).update(created_at=datetime(2026, 10, 13, 16, 0, tzinfo=dt_timezone.utc))
        Transaction.objects.filter(pk=self.unpaid_sale.pk).update(created_at=datetime(2026, 10, 14, 15, 59, 59, tzinfo=dt_timezone.utc))
        Transaction.objects.filter(pk=self.yesterday_sale.pk).update(created_at=datetime(2026, 10, 14, 16, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(self.dashboard().context['today_sales'], Decimal('141.75'))

    def test_paid_status_counts_independently_of_collection_flag(self):
        Transaction.objects.filter(pk=self.paid_sale.pk).update(collected_at_end_of_day=True)
        self.assertEqual(self.dashboard().context['today_paid'], Decimal('51.00'))
        self.unpaid_sale.payment_status = 'paid'
        self.unpaid_sale.save(update_fields=['payment_status'])
        context = self.dashboard().context
        self.assertEqual(context['today_paid'], Decimal('141.75'))
        self.assertEqual(context['today_unpaid'], Decimal('0.00'))

    def test_empty_dashboard_renders_zero_totals_and_empty_states(self):
        Transaction.objects.all().delete()
        Customer.objects.all().delete()
        InventoryItem.objects.all().delete()
        response = self.dashboard()
        self.assertEqual(response.status_code, 200)
        for key in ('today_sales', 'today_paid', 'today_unpaid', 'today_gallons', 'today_transactions', 'total_customers', 'low_stock_items'):
            with self.subTest(key=key):
                self.assertEqual(response.context[key], 0)
        self.assertIsInstance(response.context['today_sales'], Decimal)
        self.assertContains(response, 'No inventory items yet.')
        self.assertContains(response, 'No recent transactions found.')
        self.assertContains(response, '₱0.00')

    def test_existing_public_dashboard_and_protected_admin_access_are_preserved(self):
        # The existing dashboard has no login decorator. Preserve that policy.
        self.client.logout()
        self.assertEqual(self.dashboard().status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)

    def test_dashboard_is_read_only(self):
        before_sales = list(Transaction.objects.order_by('pk').values())
        before_stock = list(InventoryItem.objects.order_by('pk').values())
        before_customers = list(Customer.objects.order_by('pk').values())
        self.dashboard()
        self.assertEqual(list(Transaction.objects.order_by('pk').values()), before_sales)
        self.assertEqual(list(InventoryItem.objects.order_by('pk').values()), before_stock)
        self.assertEqual(list(Customer.objects.order_by('pk').values()), before_customers)

    def test_dashboard_data_has_no_per_transaction_related_queries(self):
        from django.test import RequestFactory
        from .views import dashboard
        request = RequestFactory().get(self.url)
        with patch('main.views.timezone.localdate', return_value=self.today), patch('main.views.render', side_effect=lambda request, template, context: context):
            with self.assertNumQueries(4):
                context = dashboard(request)
                rows = [(sale.customer.name, sale.inventory_item.name) for sale in context['recent_transactions']]
        self.assertEqual(len(rows), 3)


class InventoryV3Tests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        self.staff = get_user_model().objects.create_user(username='inventory-staff', is_staff=True)
        self.staff.user_permissions.set(Permission.objects.filter(codename__in=['add_inventoryitem', 'change_inventoryitem', 'delete_inventoryitem']))
        self.customer = Customer.objects.create(name='History Customer', address='Fictional', contact_number='N/A')
        self.item = InventoryItem.objects.create(name='History Water', unit='gallons', stock_in=100)
        self.detail_url = reverse('inventory_item_detail', args=[self.item.pk])
        self.edit_url = reverse('inventory_edit', args=[self.item.pk])
        self.delete_url = reverse('inventory_delete', args=[self.item.pk])

    def login(self):
        self.client.force_login(self.staff)

    def sale(self, quantity=5):
        return Transaction.objects.create(customer=self.customer, inventory_item=self.item, quantity=quantity, price_per_gallon=Decimal('25.00'))

    def test_history_combines_stock_logs_and_sales_newest_first(self):
        from datetime import timedelta
        from django.utils import timezone
        log = StockLog.objects.create(inventory_item=self.item, change=20, note='Recorded delivery')
        sale = self.sale()
        adjustment = StockLog.objects.create(inventory_item=self.item, change=-2, note='Existing adjustment record')
        now = timezone.now()
        StockLog.objects.filter(pk=log.pk).update(date=now - timedelta(days=2))
        Transaction.objects.filter(pk=sale.pk).update(created_at=now - timedelta(days=1))
        StockLog.objects.filter(pk=adjustment.pk).update(date=now)
        response = self.client.get(self.detail_url)
        rows = response.context['movements']
        self.assertEqual([row['type'] for row in rows], ['Adjustment', 'Sale / Stock Out', 'Stock In'])
        self.assertEqual([row['quantity'] for row in rows], [-2, -5, 20])
        self.assertContains(response, 'Recorded delivery')
        self.assertContains(response, 'Reconstructed from current sale')
        self.assertContains(response, reverse('transaction_detail', args=[sale.pk]))
        self.assertContains(response, 'Running balances cannot be reliably reconstructed')

    def test_logged_restock_appears_exactly_once_without_a_second_deduction(self):
        self.login()
        response = self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': 10, 'note': 'New receipt'})
        self.assertEqual(response.status_code, 302)
        sale = self.sale()
        for _ in range(2):
            response = self.client.get(self.detail_url)
            self.assertEqual(len(response.context['movements']), 2)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 110)
        self.assertEqual(self.item.stock_out, 5)
        self.assertEqual(StockLog.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_viewing_history_changes_no_business_records(self):
        log = StockLog.objects.create(inventory_item=self.item, change=100, note='Opening receipt')
        self.sale()
        before = {model: list(model.objects.order_by('pk').values()) for model in (InventoryItem, StockLog, Transaction, Customer)}
        self.client.get(self.detail_url)
        self.client.get(self.detail_url)
        for model, values in before.items():
            self.assertEqual(list(model.objects.order_by('pk').values()), values)

    def test_history_empty_state_does_not_invent_opening_stock(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'No stock movement history is available')
        self.assertEqual(response.context['movements'], [])
        self.assertFalse(StockLog.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock(), 100)

    def test_history_queries_do_not_grow_with_sale_count(self):
        from django.test import RequestFactory
        from .views import inventory_item_detail
        for _ in range(8):
            self.sale(1)
        request = RequestFactory().get(self.detail_url)
        with patch('main.views.render', side_effect=lambda request, template, context: context):
            with self.assertNumQueries(3):
                context = inventory_item_detail(request, self.item.pk)
        self.assertEqual(len(context['movements']), 8)

    def test_history_uses_local_timezone(self):
        from datetime import datetime, timezone as dt_timezone
        sale = self.sale()
        Transaction.objects.filter(pk=sale.pk).update(created_at=datetime(2026, 10, 13, 16, 0, tzinfo=dt_timezone.utc))
        self.assertContains(self.client.get(self.detail_url), 'Oct 14, 2026 12:00 AM')

    def test_threshold_statuses_and_dashboard_totals_match(self):
        from .inventory import stock_status
        for balance, label in ((0, 'Out of Stock'), (5, 'Low Stock'), (10, 'Low Stock'), (11, 'In Stock')):
            item = InventoryItem.objects.create(name=f'Balance {balance}', unit='bottles', stock_in=balance)
            self.assertEqual(stock_status(item), label)
        response = self.client.get(reverse('inventory_list'))
        self.assertEqual(response.context['low_stock_items'], 3)
        self.assertEqual(self.client.get(reverse('dashboard')).context['low_stock_items'], 3)
        for text in ('0 bottles', '5 bottles', '10 bottles', '11 bottles', 'bg-danger', 'bg-warning', 'bg-success', 'Details / History'):
            self.assertContains(response, text)

    def test_metadata_edits_preserve_stock_and_sales(self):
        self.login()
        sale = self.sale()
        before_sale = list(Transaction.objects.values())
        response = self.client.post(self.edit_url, {'name': 'Renamed Water', 'unit': 'gallons'})
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, 'Renamed Water')
        self.assertEqual(self.item.stock_in, 100)
        self.assertEqual(self.item.stock_out, 5)
        self.assertEqual(list(Transaction.objects.values()), before_sale)
        self.assertFalse(StockLog.objects.exists())

    def test_direct_post_cannot_change_cumulative_counts_or_make_stock_negative(self):
        self.login()
        for change in ({'stock_in': -1}, {'stock_out': -1}, {'stock_out': 101}, {'stock_in': 200}, {'stock_in': 'bad'}):
            with self.subTest(change=change):
                response = self.client.post(self.edit_url, {'name': 'Should not change', 'unit': 'gallons', **change})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.item.refresh_from_db()
                self.assertEqual(self.item.name, 'History Water')
                self.assertEqual(self.item.stock_in, 100)
                self.assertEqual(self.item.stock_out, 0)

    def test_unit_edits_cannot_relabel_existing_sale_history(self):
        self.login()
        self.sale()
        response = self.client.post(self.edit_url, {'name': self.item.name, 'unit': 'bottles'})
        self.assertContains(response, 'The unit cannot be changed')
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit, 'gallons')

    def test_unit_edits_cannot_relabel_existing_stock_logs(self):
        self.login()
        StockLog.objects.create(inventory_item=self.item, change=100)
        response = self.client.post(self.edit_url, {'name': self.item.name, 'unit': 'bottles'})
        self.assertContains(response, 'The unit cannot be changed')
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit, 'gallons')

    def test_unit_can_change_on_unused_product(self):
        self.login()
        self.assertEqual(self.client.post(self.edit_url, {'name': self.item.name, 'unit': 'bottles'}).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit, 'bottles')

    def test_sale_referenced_item_cannot_be_deleted(self):
        self.login()
        sale = self.sale()
        response = self.client.post(self.delete_url)
        self.assertContains(response, 'referenced by existing sales transactions')
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=sale.pk).exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_out, 5)

    def test_item_with_stock_history_cannot_be_deleted(self):
        self.login()
        log = StockLog.objects.create(inventory_item=self.item, change=100)
        response = self.client.post(self.delete_url)
        self.assertContains(response, 'recorded stock movement history')
        self.assertTrue(StockLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_orm_and_bulk_deletion_cannot_cascade_into_history(self):
        from django.db import transaction
        from django.db.models.deletion import ProtectedError
        self.sale()
        log = StockLog.objects.create(inventory_item=self.item, change=100)
        for delete in (self.item.delete, lambda: InventoryItem.objects.filter(pk=self.item.pk).delete()):
            with self.subTest(delete=delete), self.assertRaises(ProtectedError):
                with transaction.atomic():
                    delete()
            self.item.refresh_from_db()
            self.assertEqual(self.item.stock_out, 5)
            self.assertEqual(Transaction.objects.count(), 1)
            self.assertEqual(StockLog.objects.count(), 1)

    def test_get_is_only_confirmation_and_cannot_delete(self):
        self.login()
        self.assertContains(self.client.get(self.delete_url), 'Yes, Delete')
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_authorized_post_deletes_unused_item(self):
        self.login()
        response = self.client.post(self.delete_url)
        self.assertRedirects(response, reverse('inventory_list'))
        self.assertFalse(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_post_requires_csrf_token(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.post(self.delete_url).status_code, 403)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_anonymous_write_requests_redirect_to_existing_login(self):
        for url in (self.edit_url, self.delete_url, reverse('restock_item', args=[self.item.pk]), reverse('inventory_add')):
            for method in ('get', 'post'):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse('admin:login')))
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_non_staff_with_permissions_cannot_edit_or_delete(self):
        self.staff.is_staff = False
        self.staff.save(update_fields=['is_staff'])
        self.login()
        for url in (self.edit_url, self.delete_url):
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_staff_without_permissions_cannot_edit_or_delete(self):
        self.staff.user_permissions.clear()
        self.login()
        for url in (self.edit_url, self.delete_url):
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_change_permission_does_not_grant_delete_permission(self):
        from django.contrib.auth.models import Permission
        self.staff.user_permissions.set(Permission.objects.filter(codename='change_inventoryitem'))
        self.login()
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
        self.assertEqual(self.client.post(self.delete_url).status_code, 403)

    def test_admin_protects_history_and_exposes_counts_as_read_only(self):
        from django.contrib import admin
        from django.contrib.auth import get_user_model
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])
        self.login()
        self.sale()
        model_admin = admin.site._registry[InventoryItem]
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.staff
        self.assertIn('stock_in', model_admin.get_readonly_fields(request, self.item))
        self.assertIn('stock_out', model_admin.get_readonly_fields(request, self.item))
        self.assertIn('unit', model_admin.get_readonly_fields(request, self.item))
        self.assertTrue(model_admin.get_deleted_objects([self.item], request)[3])
        response = self.client.get(reverse('admin:main_inventoryitem_change', args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('admin:main_inventoryitem_delete', args=[self.item.pk]), {'post': 'yes'})
        self.assertContains(response, 'referenced by existing sales transactions')
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_public_overview_and_history_remain_read_only_accessible(self):
        self.assertEqual(self.client.get(reverse('inventory_list')).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertNotContains(self.client.get(reverse('inventory_list')), 'Add Inventory Item')

    def test_history_reflects_current_sale_after_edits_and_deletion_without_fake_logs(self):
        sale = self.sale()
        sale.quantity = 7
        sale.save()
        response = self.client.get(self.detail_url)
        self.assertEqual(len(response.context['movements']), 1)
        self.assertEqual(response.context['movements'][0]['quantity'], -7)
        self.assertFalse(StockLog.objects.exists())
        sale.delete()
        self.assertEqual(self.client.get(self.detail_url).context['movements'], [])
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_out, 0)

    def test_orm_deletion_protects_stock_history_without_sales(self):
        from django.db import transaction
        from django.db.models.deletion import ProtectedError
        log = StockLog.objects.create(inventory_item=self.item, change=100)
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.item.delete()
        self.assertTrue(StockLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_inactive_staff_cannot_modify_inventory(self):
        self.staff.is_active = False
        self.staff.save(update_fields=['is_active'])
        self.login()
        self.assertEqual(self.client.post(self.edit_url).status_code, 302)
        self.assertEqual(self.client.post(self.delete_url).status_code, 302)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())

    def test_admin_bulk_delete_preserves_referenced_records(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])
        self.login()
        self.sale()
        response = self.client.post(reverse('admin:main_inventoryitem_changelist'), {
            'action': 'delete_selected', '_selected_action': [str(self.item.pk)], 'post': 'yes',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk).exists())
        self.assertEqual(Transaction.objects.count(), 1)

    def test_admin_direct_post_cannot_rewrite_stock_counts(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])
        self.login()
        response = self.client.post(reverse('admin:main_inventoryitem_change', args=[self.item.pk]), {
            'name': 'Changed name', 'unit': 'gallons', 'stock_in': 1000, 'stock_out': 0, '_save': 'Save',
        })
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 100)
        self.assertEqual(self.item.name, 'History Water')


class SalesManagementV41Tests(TestCase):
    def setUp(self):
        from datetime import date
        self.day = date(2026, 10, 14)
        self.alpha = Customer.objects.create(name='Alpha Household', address='Private address', contact_number='Private phone')
        self.beta = Customer.objects.create(name='Beta Office', address='Other private address', contact_number='Other private phone')
        self.item = InventoryItem.objects.create(name='Purified Refill', unit='gallons', stock_in=100)
        self.other = InventoryItem.objects.create(name='Mineral Refill', unit='gallons', stock_in=100)
        self.paid = self.sale(self.alpha, self.item, 2, '25.50', 'paid', 'walk-in', hour=9)
        self.unpaid = self.sale(self.alpha, self.item, 3, '30.25', 'unpaid', 'delivery', hour=10)
        self.older = self.sale(self.beta, self.other, 1, '40.00', 'paid', 'delivery', day_offset=-1)
        self.url = reverse('transactions_list')

    def sale(self, customer, item, quantity, price, status, delivery, day_offset=0, hour=12):
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo
        sale = Transaction.objects.create(customer=customer, inventory_item=item, quantity=quantity, price_per_gallon=Decimal(price), payment_status=status, delivery_type=delivery)
        timestamp = datetime.combine(self.day + timedelta(days=day_offset), time(hour), ZoneInfo('Asia/Manila'))
        Transaction.objects.filter(pk=sale.pk).update(created_at=timestamp)
        return sale

    def ids(self, response):
        return [sale.pk for sale in response.context['transactions']]

    def test_public_sales_listing_loads_and_preserves_existing_links(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'main/transactions_list.html')
        self.assertTemplateUsed(response, 'main/base.html')
        for text in ('Sales Management', 'Apply Filters', 'Clear Filters', 'table-responsive', 'Filtered Transactions', 'Filtered Paid Sales', 'not money collected'):
            self.assertContains(response, text)
        for route in ('transaction_detail', 'edit_transaction', 'delete_transaction'):
            self.assertContains(response, reverse(route, args=[self.paid.pk]))
        self.assertNotContains(response, 'Private address')
        self.assertNotContains(response, 'Private phone')

    def test_customer_name_search_is_case_insensitive_and_trimmed(self):
        response = self.client.get(self.url, {'q': '  aLPHa  '})
        self.assertEqual(set(self.ids(response)), {self.paid.pk, self.unpaid.pk})
        self.assertEqual(response.context['filter_form'].cleaned_data['q'], 'aLPHa')

    def test_id_search_accepts_number_and_displayed_reference(self):
        for value in (str(self.paid.pk), f'#{self.paid.pk}'):
            with self.subTest(value=value):
                self.assertEqual(self.ids(self.client.get(self.url, {'q': value})), [self.paid.pk])

    def test_invalid_or_oversized_id_search_is_safe(self):
        for value in ('#bad', '#-1', '9' * 100, '９９９', '123xyz'):
            with self.subTest(value=value):
                response = self.client.get(self.url, {'q': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['transaction_count'], 0)

    def test_product_search(self):
        self.assertEqual(self.ids(self.client.get(self.url, {'q': 'mINeral'})), [self.older.pk])

    def test_empty_search_returns_default_listing_without_duplicates(self):
        for value in ('', '   '):
            response = self.client.get(self.url, {'q': value})
            self.assertEqual(response.context['transaction_count'], 3)
        self.alpha.name = 'Purified Customer'
        self.alpha.save()
        self.assertEqual(self.client.get(self.url, {'q': 'Purified'}).context['transaction_count'], 2)

    def test_from_date_only_is_inclusive(self):
        response = self.client.get(self.url, {'start_date': '2026-10-14'})
        self.assertEqual(set(self.ids(response)), {self.paid.pk, self.unpaid.pk})

    def test_to_date_only_is_inclusive(self):
        response = self.client.get(self.url, {'end_date': '2026-10-13'})
        self.assertEqual(self.ids(response), [self.older.pk])

    def test_date_range_is_inclusive_and_excludes_outside_dates(self):
        self.sale(self.beta, self.other, 1, '1.00', 'paid', 'walk-in', day_offset=1)
        response = self.client.get(self.url, {'start_date': '2026-10-13', 'end_date': '2026-10-14'})
        self.assertEqual(response.context['transaction_count'], 3)
        response = self.client.get(self.url, {'start_date': '2026-10-14', 'end_date': '2026-10-14'})
        self.assertEqual(response.context['transaction_count'], 2)

    def test_local_midnight_date_boundaries(self):
        from datetime import datetime, timezone as dt_timezone
        Transaction.objects.filter(pk=self.paid.pk).update(created_at=datetime(2026, 10, 13, 16, 0, tzinfo=dt_timezone.utc))
        Transaction.objects.filter(pk=self.unpaid.pk).update(created_at=datetime(2026, 10, 14, 15, 59, 59, tzinfo=dt_timezone.utc))
        Transaction.objects.filter(pk=self.older.pk).update(created_at=datetime(2026, 10, 14, 16, 0, tzinfo=dt_timezone.utc))
        response = self.client.get(self.url, {'start_date': '2026-10-14', 'end_date': '2026-10-14'})
        self.assertEqual(set(self.ids(response)), {self.paid.pk, self.unpaid.pk})

    def test_invalid_dates_show_validation_errors_instead_of_widening_results(self):
        for value in ('bad', '2026-02-30', '2026-13-01', '0000-01-01'):
            for field in ('start_date', 'end_date'):
                with self.subTest(field=field, value=value):
                    response = self.client.get(self.url, {field: value})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context['filter_form'].errors)
                    self.assertEqual(response.context['transaction_count'], 0)
                    self.assertContains(response, 'Please correct the filters')

    def test_reversed_dates_show_clear_error(self):
        response = self.client.get(self.url, {'start_date': '2026-10-15', 'end_date': '2026-10-14'})
        self.assertContains(response, 'To Date must be on or after From Date.')
        self.assertEqual(response.context['transaction_count'], 0)

    def test_customer_filter_preserves_selection(self):
        response = self.client.get(self.url, {'customer': self.beta.pk})
        self.assertEqual(self.ids(response), [self.older.pk])
        self.assertEqual(response.context['filter_form'].cleaned_data['customer'], self.beta)
        self.assertContains(response, f'value="{self.beta.pk}" selected')

    def test_invalid_or_deleted_customer_ids_are_safe(self):
        spare = Customer.objects.create(name='Deleted filter customer', address='Fictional', contact_number='N/A')
        removed_id = spare.pk
        spare.delete()
        for value in ('bad', '-1', str(removed_id), '9' * 100):
            with self.subTest(value=value):
                response = self.client.get(self.url, {'customer': value})
                self.assertEqual(response.status_code, 200)
                self.assertIn('customer', response.context['filter_form'].errors)
                self.assertEqual(response.context['transaction_count'], 0)

    def test_payment_status_filter(self):
        response = self.client.get(self.url, {'payment_status': 'unpaid'})
        self.assertEqual(self.ids(response), [self.unpaid.pk])
        self.assertEqual(response.context['unpaid_sales'], Decimal('90.75'))
        self.assertEqual(response.context['paid_sales'], Decimal('0.00'))

    def test_delivery_type_filter(self):
        response = self.client.get(self.url, {'delivery_type': 'delivery'})
        self.assertEqual(set(self.ids(response)), {self.unpaid.pk, self.older.pk})

    def test_invalid_choice_filters_are_rejected(self):
        for field in ('payment_status', 'delivery_type'):
            response = self.client.get(self.url, {field: 'unsupported'})
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context['filter_form'].errors)
            self.assertEqual(response.context['transaction_count'], 0)

    def test_combined_filters(self):
        filters = {'q': 'Purified', 'start_date': '2026-10-14', 'end_date': '2026-10-14', 'customer': self.alpha.pk, 'payment_status': 'unpaid', 'delivery_type': 'delivery'}
        response = self.client.get(self.url, filters)
        self.assertEqual(self.ids(response), [self.unpaid.pk])
        self.assertEqual(response.context['total_qty'], 3)
        self.assertEqual(response.context['total_revenue'], Decimal('90.75'))

    def test_summary_count_quantity_and_decimal_totals(self):
        response = self.client.get(self.url)
        context = response.context
        self.assertEqual(context['transaction_count'], 3)
        self.assertEqual(context['total_qty'], 6)
        self.assertEqual(context['total_revenue'], Decimal('181.75'))
        self.assertIsInstance(context['total_revenue'], Decimal)
        self.assertEqual(context['paid_sales'], Decimal('91.00'))
        self.assertEqual(context['unpaid_sales'], Decimal('90.75'))
        self.assertEqual(context['paid_sales'] + context['unpaid_sales'], context['total_revenue'])
        self.assertContains(response, '₱181.75')

    def test_daily_report_totals_match_for_same_filters(self):
        filters = {'start_date': '2026-10-14', 'end_date': '2026-10-14', 'delivery_type': 'delivery'}
        response = self.client.get(self.url, filters)
        report = self.client.get(reverse('daily_report'), {'date': '2026-10-14', 'delivery_type': 'delivery'})
        for key in ('transaction_count', 'total_qty', 'total_revenue', 'paid_sales', 'unpaid_sales'):
            self.assertEqual(response.context[key], report.context[key])

    def test_empty_results_render_zero_totals(self):
        response = self.client.get(self.url, {'q': 'No such customer or product'})
        for key in ('transaction_count', 'total_qty', 'total_revenue', 'paid_sales', 'unpaid_sales'):
            self.assertEqual(response.context[key], 0)
        self.assertIsInstance(response.context['total_revenue'], Decimal)
        self.assertContains(response, 'No transactions found.')
        self.assertContains(response, '₱0.00')

    def test_pagination_retains_filters_and_totals_cover_all_pages(self):
        from urllib.parse import parse_qs
        for _ in range(12):
            self.sale(self.alpha, self.item, 1, '1.25', 'paid', 'walk-in', hour=15)
        filters = {'q': 'Alpha', 'customer': str(self.alpha.pk), 'start_date': '2026-10-14', 'end_date': '2026-10-14', 'payment_status': 'paid', 'delivery_type': 'walk-in'}
        first = self.client.get(self.url, filters)
        second = self.client.get(self.url, {**filters, 'page': '2'})
        self.assertEqual(len(first.context['transactions']), 10)
        self.assertEqual(len(second.context['transactions']), 3)
        for response in (first, second):
            self.assertEqual(response.context['transaction_count'], 13)
            self.assertEqual(response.context['total_qty'], 14)
            self.assertEqual(response.context['total_revenue'], Decimal('66.00'))
            self.assertEqual(parse_qs(response.context['filter_query']), {key: [value] for key, value in filters.items()})
            self.assertContains(response, 'page=2' if response is first else 'page=1')
        self.assertEqual(set(self.ids(first)) & set(self.ids(second)), set())
        self.assertEqual(self.ids(first), sorted(self.ids(first), reverse=True))

    def test_query_parameters_are_url_encoded(self):
        from urllib.parse import parse_qs
        query = 'Alpha & Office + #1'
        response = self.client.get(self.url, {'q': query})
        self.assertEqual(parse_qs(response.context['filter_query'])['q'], [query])

    def test_invalid_page_numbers_are_safe(self):
        for value in ('bad', '0', '-1', '9999999999999999999999999999999999'):
            with self.subTest(page=value):
                response = self.client.get(self.url, {'page': value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['transactions'].number, 1)
                self.assertEqual(response.context['transaction_count'], 3)

    def test_existing_access_controls_remain_unchanged(self):
        from django.contrib.auth import get_user_model
        self.assertEqual(self.client.get(self.url).status_code, 200)
        user = get_user_model().objects.create_user(username='sales-viewer')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)
        self.assertEqual(self.client.get(reverse('inventory_edit', args=[self.item.pk])).status_code, 403)

    def test_get_requests_cause_no_sales_inventory_or_customer_mutation(self):
        models = (Transaction, InventoryItem, Customer, StockLog)
        before = {model: list(model.objects.order_by('pk').values()) for model in models}
        for filters in ({}, {'q': 'Alpha'}, {'start_date': 'bad'}, {'payment_status': 'unpaid'}, {'page': '2'}):
            self.client.get(self.url, filters)
        for model, records in before.items():
            self.assertEqual(list(model.objects.order_by('pk').values()), records)

    def test_page_data_uses_aggregate_count_and_related_loading(self):
        from django.test import RequestFactory
        from .views import transactions_list
        request = RequestFactory().get(self.url)
        with patch('main.views.render', side_effect=lambda request, template, context: context):
            with self.assertNumQueries(2):
                context = transactions_list(request)
                rows = [(sale.customer.name, sale.inventory_item.name) for sale in context['transactions']]
        self.assertEqual(len(rows), 3)
