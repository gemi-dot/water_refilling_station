# Isolated client demonstration environment

These tools are local administrative management commands, not public endpoints. Do not run them against a database containing real records. Initialization, seeding, and demo-period changes require the owner's approval. They have not been run against the persistent application databases during implementation.

## Database selection and verification

Normal execution continues using the existing database configuration. Only the exact environment value `WATERSTATION_DEMO_DB=1` opts into `BASE_DIR/db.demo.sqlite3` and replaces the entire database mapping with a dedicated SQLite backend. It does not copy records or reuse PostgreSQL/MySQL configuration. Use the flag for every demo command and for the demo server; omitting it returns to the normal database.

Inspect the selected configuration without initializing a database:

```bash
WATERSTATION_DEMO_DB=1 python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default'])"
```

Confirm the result is SQLite and points to this project's `db.demo.sqlite3`, not `db.sqlite3`. Do not rename or copy an existing database into that path. Both new commands independently verify the opt-in, configured backend and path, absence of symlinks/hardlinks, and SQLite's actual connected file. They reject attached databases. They refuse an absent database before opening it; a dry-run cannot initialize it accidentally. The demo database and its `-journal`, `-wal`, and `-shm` files are Git-ignored.

The first seed requires an empty business dataset: no customers, inventory, sales, or stock logs. Both commands reject unrecognized business records, even in a file named `db.demo.sqlite3`. Auth accounts and demo settings are not copied from the normal database. Do not enter actual customer information in this environment.

After isolation review and explicit approval, initialize **only** the dedicated database with the existing migrations:

```bash
WATERSTATION_DEMO_DB=1 python manage.py migrate
```

No new model, table, or migration is required for these tools. The commands require the existing application, Django auth, content types, and admin tables.

## Preview and seed sample records

After the dedicated database is initialized, preview without writing records:

```bash
WATERSTATION_DEMO_DB=1 python manage.py seed_demo_data --dry-run
```

After approval, seed:

```bash
WATERSTATION_DEMO_DB=1 python manage.py seed_demo_data
```

The seed is deterministic: 12 visibly fictional customers, 3 refill inventory items, 40 sales across October 12–15, 2026, and 3 initial stock logs. Names carry `[DEMO v1]`; addresses say they are fictional; contact fields contain `NOT A REAL NUMBER`. All inventory uses gallons, so the daily report's gallon total is meaningful. Bottled items are intentionally omitted because their quantities would be pieces, not gallons.

Every sale is validated and saved through the existing `Transaction.save()` stock-adjustment logic. Initial receipts are recorded as stock logs. Sales already adjust stock through their normal model logic; no extra sale stock log is invented. Historical `created_at` values are assigned with a timestamp-only queryset update **after** normal creation; this never changes sale quantity, item, amount, or stock and avoids a second stock deduction. Dates are timezone-aware Asia/Manila values.

All seed creation and the ownership manifest are in one database transaction. A failure rolls everything back. A compact versioned manifest in an initial stock log's existing `note` field stores record counts and a SHA-256 fingerprint of the original business dataset. Customer notes remain readable and contain no administrative payload. Repeated execution verifies the complete dataset and reports zero new records. It never overwrites existing records. Changed, missing, added, malformed, or unmarked business records cause refusal; there is no destructive cleanup option. The manifest is an administrative safeguard, not cryptographic protection against a malicious database administrator.

If you edit sample records during a demonstration, subsequent seeding and period resets conservatively refuse that changed dataset. Review it manually; the commands do not repair it automatically.

## Controlled demo-period reset

Preview the current configuration and a proposed fresh period:

```bash
WATERSTATION_DEMO_DB=1 python manage.py reset_demo_period --days 30 --dry-run
```

After reviewing the preview and obtaining approval:

```bash
WATERSTATION_DEMO_DB=1 python manage.py reset_demo_period --days 30 --confirm
```

An explicit integer duration of 1–365 days is required. Without `--confirm`, only `--dry-run` is allowed. The flags are mutually exclusive. A confirmed reset sets `demo_start_date` to now, `demo_duration_days` to the requested duration, and `is_active` to true, using the existing model semantics. It starts a fresh period; it does not add days to the previous expiry. An existing singleton is updated in place, or one is created if none exists. Multiple settings rows cause refusal. It never modifies normal-database activation or any external licensing service.

The same transaction writes a Django admin `LogEntry` with the previous and resulting settings, local operating-system account name, command name, and demo database path. A reserved `__waterstation_demo_audit__` account is created only inside this demo database for audit attribution; it is inactive, has no usable password, and has no staff or superuser permissions. Existing accounts are not modified. A reserved-name collision with an enabled account causes refusal. An audit-write failure rolls back the period change. Dry-runs create no settings, users, or logs.

The repository currently has the expiration middleware commented out in `MIDDLEWARE`. These tools do not enable, disable, or bypass middleware, change public routes, or add a reset button. The existing `init_demo` command is unchanged and is **not** a replacement for this guarded reset workflow; it lacks these isolation checks. Demo restrictions and any production licensing policy must be reviewed separately before deployment.

## Expected figures

These figures are derived from the deterministic sample rows; the report itself aggregates actual stored records.

| Scope | Transactions | Gallons | Sales | Paid sales | Unpaid sales | Paid cash | Paid check | Paid online |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| October 12–15, 2026 | 40 | 100 | ₱3,480.00 | ₱2,800.00 | ₱680.00 | ₱700.00 | ₱1,260.00 | ₱840.00 |
| October 14, 2026 | 10 | 23 | ₱835.00 | ₱720.00 | ₱115.00 | ₱150.00 | ₱360.00 | ₱210.00 |

| Inventory item | Stock in | Stock out | Remaining gallons |
| --- | ---: | ---: | ---: |
| Purified Water Refill | 250 | 35 | 215 |
| Mineral Water Refill | 250 | 32 | 218 |
| Alkaline Water Refill | 250 | 33 | 217 |

Paid sales describe current sale payment status; no payment collection timestamp exists, so they are not verified daily receipts.

After approval and initialization, run the isolated demo application:

```bash
WATERSTATION_DEMO_DB=1 python manage.py runserver
```

Open `/reports/daily/?date=2026-10-14`. If admin access is needed, explicitly create a new demo-only superuser using `createsuperuser` with the same demo flag; never copy the existing superuser. No demo account is created automatically by the seeder.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test main -v 2
git diff --check
git diff --stat
git status --short
```

Command integration tests migrate and exercise disposable file-backed SQLite databases in temporary directories. They do not seed the project's persistent demo database or change its existing database or superuser. Existing inventory and report tests remain intact. No dependencies are added.
