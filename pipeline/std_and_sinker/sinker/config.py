import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

SRC = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    bootstrap_servers: str
    input_topics: tuple[str, ...]
    group_id: str
    mongo_uri: str
    mongo_database: str
    contracts_dir: Path = SRC / "contracts"
    routes_file: Path = SRC / "contracts/routes.json"
    offset_reset: str = "earliest"
    delivery_timeout: float = 120.0
    record_retries: int = 3
    retry_backoff: float = 1.0
    security_protocol: str = "PLAINTEXT"
    ssl_ca_location: str | None = None
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None

    @classmethod
    def from_env(cls, env_file):
        env_file = Path(env_file).resolve()
        values = {**dotenv_values(env_file), **os.environ}

        def required(name):
            value = values.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing required setting: {name}")
            return value.strip()

        def csv(name):
            items = [item.strip() for item in required(name).split(",")]
            if any(not item for item in items):
                raise ValueError(f"Empty list entry: {name}")
            return tuple(dict.fromkeys(items))

        def path(name, fallback):
            value = values.get(name)
            if not value:
                return fallback
            candidate = Path(value)
            return candidate if candidate.is_absolute() else env_file.parent / candidate

        reset = values.get("KAFKA_AUTO_OFFSET_RESET", "earliest")
        if reset not in ("earliest", "latest", "error"):
            raise ValueError("Invalid KAFKA_AUTO_OFFSET_RESET")
        timeout = float(values.get("KAFKA_DELIVERY_TIMEOUT_SECONDS", "120"))
        retries = int(values.get("STD_SINKER_RECORD_RETRIES", "3"))
        backoff = float(values.get("STD_SINKER_RETRY_BACKOFF_SECONDS", "1"))
        if not 0 < timeout <= 120 or not 1 <= retries <= 3 or not 0 <= backoff <= 10:
            raise ValueError("Invalid timeout/retry settings")
        return cls(
            bootstrap_servers=",".join(csv("KAFKA_BOOTSTRAP_SERVERS")),
            input_topics=csv("STD_SINKER_INPUT_TOPICS"),
            group_id=required("STD_SINKER_CONSUMER_GROUP_ID"),
            mongo_uri=required("MONGODB_URI"),
            mongo_database=required("MONGODB_DATABASE"),
            contracts_dir=path("STD_SINKER_CONTRACTS_DIR", SRC / "contracts"),
            routes_file=path("STD_SINKER_ROUTES_FILE", SRC / "contracts/routes.json"),
            offset_reset=reset, delivery_timeout=timeout,
            record_retries=retries, retry_backoff=backoff,
            security_protocol=values.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            ssl_ca_location=values.get("KAFKA_SSL_CA_LOCATION"),
            sasl_mechanism=values.get("KAFKA_SASL_MECHANISM"),
            sasl_username=values.get("KAFKA_SASL_USERNAME"),
            sasl_password=values.get("KAFKA_SASL_PASSWORD"),
        )

    def connection_config(self):
        result = {
            "bootstrap.servers": self.bootstrap_servers,
            "security.protocol": self.security_protocol,
        }
        for key, value in (
            ("ssl.ca.location", self.ssl_ca_location),
            ("sasl.mechanism", self.sasl_mechanism),
            ("sasl.username", self.sasl_username),
            ("sasl.password", self.sasl_password),
        ):
            if value:
                result[key] = value
        return result

    def consumer_config(self):
        return {
            **self.connection_config(),
            "group.id": self.group_id,
            "enable.auto.offset.store": False,
            "enable.auto.commit": False,
            "auto.offset.reset": self.offset_reset,
            "max.poll.interval.ms": 600000,
        }
