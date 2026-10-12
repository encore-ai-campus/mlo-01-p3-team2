import json
import time

from confluent_kafka import Producer


class KafkaPublisher:
    def __init__(self, settings):
        self.timeout = settings.delivery_timeout
        self.producer = Producer({
            **settings.connection_config(), "acks": "all", "enable.idempotence": True,
            "compression.type": "zstd", "message.send.max.retries": 2147483647,
            "retry.backoff.ms": 100, "retry.backoff.max.ms": 1000,
            "delivery.timeout.ms": int(self.timeout * 1000),
        })

    def publish(self, topic, key, value):
        reports = []

        def delivered(error, _message):
            reports.append(error)

        manifest = value["std_manifest"]
        self.producer.produce(
            topic=topic, key=key.encode("utf-8"),
            value=json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers=[
                ("event_type", manifest["event_type"].encode("utf-8")),
                ("std_schema_version", manifest["std_schema_version"].encode("utf-8")),
            ],
            on_delivery=delivered,
        )
        deadline = time.monotonic() + self.timeout + 2
        while not reports and time.monotonic() < deadline:
            self.producer.poll(0.1)
        if not reports:
            raise TimeoutError("Std Kafka delivery acknowledgement timed out")
        if reports[0] is not None:
            raise RuntimeError("Std Kafka delivery failed")

    def close(self):
        self.producer.flush(5)
