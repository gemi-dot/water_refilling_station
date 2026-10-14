# Inventory V3 Phase 2

## Existing architecture

`InventoryItem.current_stock()` returns cumulative `stock_in - stock_out`. The model already rejects negative counts, stock-out above stock-in, and stock-out below recorded sales quantities. Sale creation, edits, and deletion update stock atomically, including restoring stock on item changes or deletion. Those methods and existing stock reversal signals are unchanged.

`StockLog` records restocks and supports signed manual changes. Sales do not create immutable stock movement logs. Previously, inventory forms could rewrite cumulative counts without recording a movement; all inventory write views were public; deleting an item could cascade through its sales and stock logs.

## History and status

The existing item details route now shows a single read-only timeline, newest first:

- Positive `StockLog.change`: recorded Stock In.
- Zero/negative `StockLog.change`: recorded Adjustment.
- Current `Transaction` quantities: Sale / Stock Out, explicitly labeled as reconstructed from the current sale record at its original date.

Viewing the timeline creates no records and changes no stock. Customer references are loaded with `select_related`, and all displayed times use Django's local timezone. Each overview item links to its details/history page.

This is not a complete audit ledger. Unlogged opening stock, prior direct edits, later sale edits, deleted sales, and earlier item assignments cannot be recovered. No historical running balance or missing timestamp is invented. Editing or deleting a sale updates/removes the corresponding reconstructed row; it does not produce a fabricated stock log. A complete immutable ledger would require separate design and approval before any schema change.

`main/inventory.py` centralizes the display-only 10-unit threshold. Zero stock is Out of Stock (red); 1–10 units is Low Stock (yellow); above 10 is In Stock (green). Dashboard and inventory low-stock counts include zero-stock items and use the same threshold. Actual item units are displayed; there is no gallon-to-bottle conversion.

## Editing and stock additions

The Edit page updates product name and unit only. Cumulative counts are displayed read-only. Direct POST attempts to change those counts are rejected server-side. The unit cannot change after a sale or stock log references the product, preventing historical quantities from being relabeled.

The existing Restock workflow remains the approved stock-addition path and still creates its stock log and updates stock in one transaction. No new adjustment workflow is introduced. Negative corrections or reconciliation of older unlogged counts need a separately reviewed auditable process; the Edit page cannot perform them. Django admin also keeps cumulative counts read-only on existing items and protects historical units.

Initial counts on a newly created item remain supported and validated by the existing form/model. Those initial counts are not automatically converted into historical movement records; the timeline explains that limitation.

## Deletion

Items referenced by sales or stock logs cannot be deleted. The confirmation page explains which history prevents deletion and provides no destructive submission button. The overview labels protected items.

Eligible item deletion requires an authorized POST with CSRF protection. GET only displays confirmation. Checks run inside a transaction, and a pre-delete protection signal also covers direct Django ORM deletes and bulk deletes. Django admin's deletion preview explicitly marks these items protected, including bulk selections. No foreign key, migration, stock balance, or sales record is rewritten.

For ORM code catching a deletion failure inside an existing transaction, put the deletion in a nested `transaction.atomic()` block and catch the exception outside that nested block so the caller's transaction remains usable.

## Minimal staff policy

Previously there was no inventory-write authorization policy. Inventory writes now require an authenticated, active staff account plus Django's corresponding existing permission:

| Action | Required permission |
| --- | --- |
| Add inventory | `main.add_inventoryitem` |
| Edit product details or restock | `main.change_inventoryitem` |
| Delete eligible inventory | `main.delete_inventoryitem` |

The existing admin login is used for anonymous users; authenticated users without the staff status or required permission receive HTTP 403. Existing superusers meet the permission requirements. Public read-only inventory pages and the dashboard retain their existing access behavior. No user, password, group, or permission assignment is changed automatically.

An existing administrator can assign staff status and these permissions through Django admin before a staff member uses the write controls. Buttons reflect permissions, but server-side checks enforce them independently. The old tests retain their assertions; five inventory write tests now explicitly sign in an authorized test staff account.

## Safety and validation

No migrations or dependencies are introduced. Database selection and demo settings are unchanged. No persistent demo seed or reset command is run. Automated command tests inherited from earlier phases run only in their disposable test databases. Existing `db.sqlite3`, `db.demo.sqlite3`, and `db.sqlite3.backup` are checked by hashes before and after validation.

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test main
git diff --check
```

The review items are the new staff permission policy, historical limitations, and any future need for a complete audit/reconciliation workflow. Other existing customer and sales write routes retain their previous authorization behavior; broader access control is outside this inventory phase.
