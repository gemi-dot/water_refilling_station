"""Fail closed before opening a connection for either administrative demo tool."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections


def require_demo_database():
    if getattr(settings, 'WATERSTATION_DEMO_DB', False) is not True:
        raise CommandError('Refusing operation: explicitly select WATERSTATION_DEMO_DB=1.')
    if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
        raise CommandError('Refusing operation: production database backends are not allowed.')
    connection = connections['default']
    config = connection.settings_dict
    expected = Path(settings.BASE_DIR).absolute() / 'db.demo.sqlite3'
    configured = Path(str(config['NAME'])).absolute()
    if config['ENGINE'] != 'django.db.backends.sqlite3' or configured != expected:
        raise CommandError('Refusing operation: only the designated db.demo.sqlite3 SQLite database is allowed.')
    if expected.is_symlink() or expected.resolve() != expected:
        raise CommandError('Refusing operation: the demo database path must not use symlinks.')
    if not expected.is_file():
        raise CommandError('Demo database is not initialized. Review isolation, then run migrations in demo mode.')
    normal = Path(settings.BASE_DIR) / 'db.sqlite3'
    if normal.exists() and expected.samefile(normal):
        raise CommandError('Refusing operation: demo database aliases the normal database.')
    if expected.stat().st_nlink != 1:
        raise CommandError('Refusing operation: demo database must not be a hard link.')
    # Confirm the live SQLite connection, not just Django settings or a filename.
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA database_list')
        databases = cursor.fetchall()
    main_paths = [Path(name).absolute() for _, label, name in databases if label == 'main' and name]
    if main_paths != [expected] or any(label not in ('main', 'temp') for _, label, _ in databases):
        raise CommandError('Refusing operation: live connection is not exclusively the designated demo database.')
    return expected
