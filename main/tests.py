from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse

from .forms import InventoryItemForm, TransactionForm
from .models import Customer, InventoryItem, StockLog, Transaction


class InventoryTransactionTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Customer', address='Manila', contact_number='123')
        self.item = InventoryItem.objects.create(name='Water', unit='gallons', stock_in=20)
        self.other = InventoryItem.objects.create(name='Bottled water', unit='pcs', stock_in=10)

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
        self.sale()
        response = self.client.post(reverse('inventory_edit', args=[self.item.pk]), {
            'name': 'Water', 'unit': 'gallons', 'stock_in': 20, 'stock_out': 0,
        })
        self.assertContains(response, 'Stock out cannot be less')
        self.balances(5)

    def test_restock_adds_inventory_and_log(self):
        self.sale()
        response = self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': 4, 'note': 'Delivery'})
        self.assertEqual(response.status_code, 302)
        self.balances(5)
        self.assertEqual(self.item.stock_in, 24)
        log = StockLog.objects.get()
        self.assertEqual(log.change, 4)
        self.assertEqual(log.note, 'Delivery')

    def test_restock_failure_rolls_back_inventory(self):
        with patch('main.views.StockLog.objects.create', side_effect=DatabaseError('log failed')):
            with self.assertRaises(DatabaseError):
                self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': 4})
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 20)
        self.assertFalse(StockLog.objects.exists())

    def test_invalid_restock_does_not_change_inventory(self):
        for quantity in (0, -1, 'invalid'):
            response = self.client.post(reverse('restock_item', args=[self.item.pk]), {'quantity': quantity})
            self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_in, 20)
        self.assertFalse(StockLog.objects.exists())
