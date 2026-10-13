import logging
import time
from collections import Counter

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition

from .contracts import ContractRegistry
from .errors import RetryableIOError, is_retryable_io
from .kafka import KafkaPublisher
from .mongo import MongoSink
from .processor import Processor, Record

LOG = logging.getLogger(__name__)


def record_from_message(message):
    return Record(
        topic=message.topic(), partition=message.partition(), offset=message.offset(),
        value=message.value(), key=message.key(),
        timestamp=message.timestamp()[1], headers=message.headers(),
    )


def handle_and_commit(processor, record, consumer):
    outcome = processor.handle(record)
    try:
        committed = consumer.commit(
            offsets=[TopicPartition(record.topic, record.partition, record.offset + 1)],
            asynchronous=False,
        )
        for partition in committed or []:
            if partition.error is not None:
                raise KafkaException(partition.error)
    except KafkaException as error:
        # Explicit offsets are valid here; lost group state requires a new consumer.
        if (error.args and isinstance(error.args[0], KafkaError)
                and not error.args[0].fatal() and error.args[0].code() == KafkaError._STATE):
            raise RetryableIOError("Raw offset commit lost consumer group state") from error
        raise
    return outcome


def close_connections(consumer, publisher, sink):
    # A cleanup failure must neither hide the original error nor leak other clients.
    for name, client in (("consumer", consumer), ("publisher", publisher), ("mongo", sink)):
        if client is not None:
            try:
                client.close()
            except Exception as error:
                LOG.warning("Connection cleanup failed client=%s error_type=%s", name, type(error).__name__)


def run_worker(settings, max_messages=None, idle_timeout=None):
    registry = ContractRegistry(settings.contracts_dir, settings.routes_file)
    registry.validate_topics(settings.input_topics)
    counts = Counter()
    outcomes = []
    processed = 0
    recovery_attempts = 0
    recovery_delay = settings.recovery_backoff
    while max_messages is None or processed < max_messages:
        sink = consumer = publisher = processor = None
        try:
            sink = MongoSink(settings.mongo_uri, settings.mongo_database, registry.parser_versions)
            publisher = KafkaPublisher(settings)
            consumer = Consumer(settings.consumer_config())
            consumer.subscribe(list(settings.input_topics))
            processor = Processor(registry, sink, publisher)
            last_message = time.monotonic()
            while max_messages is None or processed < max_messages:
                message = consumer.poll(0.5)
                if message is None:
                    if idle_timeout is not None and time.monotonic() - last_message >= idle_timeout:
                        return {"processed": processed, "counts": dict(counts), "outcomes": outcomes}
                    continue
                if message.error():
                    if message.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise KafkaException(message.error())
                record = record_from_message(message)
                last_message = time.monotonic()
                for attempt in range(settings.record_retries):
                    try:
                        outcome = handle_and_commit(processor, record, consumer)
                        break
                    except Exception as error:
                        if not is_retryable_io(error):
                            raise
                        # Never poll/commit a later record past this failed record.
                        LOG.warning(
                            "I/O retry topic=%s partition=%s offset=%s attempt=%s error_type=%s",
                            record.topic, record.partition, record.offset, attempt + 1, type(error).__name__,
                        )
                        if attempt + 1 == settings.record_retries:
                            raise
                        time.sleep(settings.retry_backoff)
                counts[outcome.status] += 1
                processed += 1
                if recovery_attempts:
                    LOG.info("I/O recovered reconnects=%s processed=%s", recovery_attempts, processed)
                recovery_attempts = 0
                recovery_delay = settings.recovery_backoff
                if outcome.status == "CONFLICT":
                    LOG.error(
                        "EVENT_UUID_CONFLICT topic=%s partition=%s offset=%s event_uuid=%s",
                        record.topic, record.partition, record.offset, outcome.event_uuid,
                    )
                # Continuous workers keep counters, not an ever-growing per-event history.
                if max_messages is not None:
                    outcomes.append({
                        "topic": record.topic, "partition": record.partition, "offset": record.offset,
                        "status": outcome.status, "event_uuid": outcome.event_uuid,
                        "error_code": outcome.error_code,
                    })
        except Exception as error:
            if not is_retryable_io(error):
                raise
            recovery_attempts += 1
            LOG.error(
                "I/O recovery waiting reconnect=%s delay_seconds=%s error_type=%s processed=%s",
                recovery_attempts, recovery_delay, type(error).__name__, processed,
            )
        finally:
            close_connections(consumer, publisher, sink)
            # Release all old clients even when the next startup fails before Processor is created.
            sink = consumer = publisher = processor = None
        if max_messages is None or processed < max_messages:
            # Leave the group before waiting; replay from committed offsets with a fresh consumer.
            time.sleep(recovery_delay)
            recovery_delay = min(recovery_delay * 2, settings.recovery_backoff_max)
    return {"processed": processed, "counts": dict(counts), "outcomes": outcomes}
