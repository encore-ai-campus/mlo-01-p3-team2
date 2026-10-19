"""Disposable file database for the concurrency verification run."""
from .settings import *

KAFKA_BOOTSTRAP_SERVERS = ""
# Legacy presence tests send coordinates. Production always uses server input;
# authoritative-controller tests explicitly override this compatibility setting.
CAMPUS_TEST_LEGACY_MOVEMENT = True
CAMPUS_SESSION_CLEANUP_ENABLED = False
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'test-kafka-source.sqlite3',
    'TEST': {'NAME': str(BASE_DIR / 'test-kafka.sqlite3')}}}
