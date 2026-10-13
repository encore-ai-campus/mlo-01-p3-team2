import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    bootstrap_servers: str
    input_topics: tuple
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    checkpoint: str
    registry_path: str
    master: str = "local[2]"
    initial_offsets: str = "earliest"
    write_partitions: int = 3
    batch_size: int = 100
    max_offsets: int = 1000
    trigger_seconds: int = 5
    security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_jaas_config: str | None = None
    kafka_ssl_truststore_location: str | None = None
    kafka_ssl_truststore_password: str | None = None
    mysql_ssl_ca: str | None = None

    @classmethod
    def from_env(cls, path):
        path = Path(path).resolve()
        values = {**dotenv_values(path), **os.environ}

        def required(name):
            value = values.get(name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"Missing setting: {name}")
            return value.strip()

        def positive(name, default, maximum):
            value = int(values.get(name, default))
            if not 1 <= value <= maximum:
                raise ValueError(f"Invalid setting: {name}")
            return value

        def resolved(value):
            if "://" in value:
                return value
            candidate = Path(value)
            return str(candidate if candidate.is_absolute() else path.parent / candidate)

        topics = tuple(dict.fromkeys(item.strip() for item in required("SPARK_INPUT_TOPICS").split(",")))
        if any(not topic for topic in topics):
            raise ValueError("Empty input topic")
        database = required("MYSQL_DATABASE")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
            raise ValueError("Invalid MySQL database identifier")
        initial = values.get("SPARK_STARTING_OFFSETS", "earliest")
        if initial not in ("earliest", "latest"):
            raise ValueError("SPARK_STARTING_OFFSETS must be earliest/latest")
        return cls(
            bootstrap_servers=required("KAFKA_BOOTSTRAP_SERVERS"), input_topics=topics,
            mysql_host=required("MYSQL_HOST"), mysql_port=positive("MYSQL_PORT", 3306, 65535),
            mysql_database=database, mysql_user=required("MYSQL_USER"), mysql_password=required("MYSQL_PASSWORD"),
            checkpoint=resolved(required("SPARK_CHECKPOINT_LOCATION")),
            registry_path=resolved(values.get("SPARK_REGISTRY_FILE", str(ROOT / "contracts/registry.json"))),
            master=values.get("SPARK_MASTER", "local[2]"), initial_offsets=initial,
            write_partitions=positive("SPARK_WRITE_PARTITIONS", 3, 16),
            batch_size=positive("MYSQL_WRITE_BATCH_SIZE", 100, 1000),
            max_offsets=positive("SPARK_MAX_OFFSETS_PER_TRIGGER", 1000, 1000000),
            trigger_seconds=positive("SPARK_TRIGGER_SECONDS", 5, 300),
            security_protocol=values.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            kafka_sasl_mechanism=values.get("KAFKA_SASL_MECHANISM"),
            kafka_sasl_jaas_config=values.get("KAFKA_SASL_JAAS_CONFIG"),
            kafka_ssl_truststore_location=values.get("KAFKA_SSL_TRUSTSTORE_LOCATION"),
            kafka_ssl_truststore_password=values.get("KAFKA_SSL_TRUSTSTORE_PASSWORD"),
            mysql_ssl_ca=values.get("MYSQL_SSL_CA"),
        )

    def mysql_config(self):
        result = {"host": self.mysql_host, "port": self.mysql_port, "user": self.mysql_user,
                  "password": self.mysql_password, "database": self.mysql_database, "charset": "utf8mb4",
                  "autocommit": False, "connect_timeout": 10, "read_timeout": 30, "write_timeout": 30}
        if self.mysql_ssl_ca:
            result.update(ssl_ca=self.mysql_ssl_ca, ssl_verify_cert=True, ssl_verify_identity=True)
        return result

    def kafka_options(self):
        result = {"kafka.bootstrap.servers": self.bootstrap_servers,
                  "subscribe": ",".join(self.input_topics), "includeHeaders": "true", "failOnDataLoss": "true",
                  "startingOffsets": self.initial_offsets, "maxOffsetsPerTrigger": str(self.max_offsets),
                  "kafka.security.protocol": self.security_protocol}
        for name, value in (
            ("kafka.sasl.mechanism", self.kafka_sasl_mechanism),
            ("kafka.sasl.jaas.config", self.kafka_sasl_jaas_config),
            ("kafka.ssl.truststore.location", self.kafka_ssl_truststore_location),
            ("kafka.ssl.truststore.password", self.kafka_ssl_truststore_password),
        ):
            if value:
                result[name] = value
        return result
