"""Single-process Kafka publisher for durable outbox events, including movement."""
import json
import logging
import os
import threading
import time

from django.conf import settings
from django.db import close_old_connections, connections
from django.utils import timezone

from .events import build_envelope
from .models import EventOutbox

logger = logging.getLogger(__name__)
_worker = None
_worker_lock = threading.Lock()
_stop = threading.Event()


def producer_config():
    config = {
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
        "enable.idempotence": True,
        "compression.type": "zstd",
        "message.send.max.retries": 2147483647,
        "retry.backoff.ms": 100,
        "retry.backoff.max.ms": 1000,
        "delivery.timeout.ms": 120000,
    }
    config.update({key: value for key, value in {
        "security.protocol": settings.KAFKA_SECURITY_PROTOCOL,
        "sasl.mechanism": settings.KAFKA_SASL_MECHANISM,
        "sasl.username": settings.KAFKA_SASL_USERNAME,
        "sasl.password": settings.KAFKA_SASL_PASSWORD,
    }.items() if value})
    return config


def _deliver(producer, topic, key, value):
    result = {"done": False, "error": None}

    def callback(error, message):
        result["error"] = error
        result["done"] = True

    producer.produce(
        topic,
        key=str(key).encode("utf-8"),
        value=json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        on_delivery=callback,
    )
    deadline = time.monotonic() + 125
    while not result["done"] and time.monotonic() < deadline and not _stop.is_set():
        producer.poll(0.25)
    if not result["done"]:
        raise TimeoutError("Kafka delivery acknowledgement timed out")
    if result["error"] is not None:
        raise RuntimeError(str(result["error"]))


def _publisher_loop(stop):
    try:
        from confluent_kafka import Producer
    except ImportError:
        logger.error("Kafka publisher is disabled: install project requirements to enable confluent-kafka")
        return
    try:
        producer = Producer(producer_config())
    except Exception:
        logger.exception("Could not configure Kafka producer")
        return

    while not stop.is_set():
        close_old_connections()
        try:
            row = EventOutbox.objects.filter(published_at__isnull=True).order_by("created_at", "event_uuid").first()
            if row is None:
                producer.poll(0.25)
                stop.wait(0.25)
                continue
            if row.payload_json is None:
                row.payload_json = build_envelope(row.event_uuid, row.event_type, row.occurred_at, row.raw_data)
                if row.payload_json is None:
                    logger.error("Outbox event remains pending until xxhash is installed: event=%s", row.event_uuid)
                    stop.wait(5)
                    continue
                EventOutbox.objects.filter(event_uuid=row.event_uuid, payload_json__isnull=True).update(
                    payload_json=row.payload_json
                )
            try:
                _deliver(producer, row.topic, row.message_key, row.payload_json)
            except Exception:
                EventOutbox.objects.filter(event_uuid=row.event_uuid, published_at__isnull=True).update(
                    retry_count=row.retry_count + 1
                )
                logger.warning("Kafka delivery failed; event remains in outbox: event=%s topic=%s",
                               row.event_uuid, row.topic)
                stop.wait(1)
                continue
            EventOutbox.objects.filter(event_uuid=row.event_uuid, published_at__isnull=True).update(
                published_at=timezone.now()
            )
        except Exception:
            logger.exception("Raw event publisher loop failed; pending events will be retried")
            stop.wait(1)
        finally:
            connections.close_all()
    try:
        producer.flush(5)
    except Exception:
        logger.exception("Kafka producer could not flush during shutdown")


def start_outbox_publisher():
    global _worker
    if not settings.KAFKA_BOOTSTRAP_SERVERS:
        return None
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        if not os.environ.get("RUN_MAIN") == "true" and "runserver" in os.sys.argv and "--noreload" not in os.sys.argv:
            return None
        _stop.clear()
        _worker = threading.Thread(
            target=_publisher_loop, args=(_stop,), name="campus-kafka-outbox", daemon=True,
        )
        _worker.start()
    return _worker
