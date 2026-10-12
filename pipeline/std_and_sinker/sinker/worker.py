import logging
import time
from collections import Counter

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition

from .contracts import ContractRegistry
from .errors import ResultConflict
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
    committed = consumer.commit(
        offsets=[TopicPartition(record.topic, record.partition, record.offset + 1)],
        asynchronous=False,
    )
    if any(partition.error is not None for partition in (committed or [])):
        raise RuntimeError("Raw offset commit failed")
    return outcome


def run_worker(settings, max_messages=None, idle_timeout=None):
    registry = ContractRegistry(settings.contracts_dir, settings.routes_file)
    registry.validate_topics(settings.input_topics)
    counts = Counter()
    outcomes = []
    processed = 0
    sink = MongoSink(settings.mongo_uri, settings.mongo_database, registry.parser_versions)
    consumer = None
    publisher = None
    try:
        publisher = KafkaPublisher(settings)
        consumer = Consumer(settings.consumer_config())
        consumer.subscribe(list(settings.input_topics))
        last_message = time.monotonic()
        while max_messages is None or processed < max_messages:
            message = consumer.poll(0.5)
            if message is None:
                if idle_timeout is not None and time.monotonic() - last_message >= idle_timeout:
                    break
                continue
            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(message.error())
            record = record_from_message(message)
            last_message = time.monotonic()
            processor = Processor(registry, sink, publisher)
            for attempt in range(settings.record_retries):
                try:
                    outcome = handle_and_commit(processor, record, consumer)
                    break
                except ResultConflict:
                    raise
                except Exception:
                    # Keep this record; never poll/commit a later record past it.
                    LOG.warning("I/O retry topic=%s partition=%s offset=%s attempt=%s",
                                record.topic, record.partition, record.offset, attempt + 1)
                    if attempt + 1 == settings.record_retries:
                        raise
                    time.sleep(settings.retry_backoff)
            counts[outcome.status] += 1
            processed += 1
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
        return {"processed": processed, "counts": dict(counts), "outcomes": outcomes}
    finally:
        if consumer is not None:
            consumer.close()
        if publisher is not None:
            publisher.close()
        sink.close()
