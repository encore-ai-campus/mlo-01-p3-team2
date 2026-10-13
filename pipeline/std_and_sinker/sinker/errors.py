from confluent_kafka import KafkaError, KafkaException
from pymongo.errors import ConnectionFailure, ExecutionTimeout, PyMongoError, WTimeoutError


class RetryableIOError(RuntimeError):
    """An acknowledgement was not received; replay without advancing the offset."""


# librdkafka's local transport/timeout errors do not always set retriable().
_RECOVERABLE_KAFKA_CODES = {
    getattr(KafkaError, name) for name in (
        "_TRANSPORT", "_ALL_BROKERS_DOWN", "_RESOLVE", "_MSG_TIMED_OUT",
        "_TIMED_OUT", "_TIMED_OUT_QUEUE", "_QUEUE_FULL", "_MAX_POLL_EXCEEDED",
        "_WAIT_COORD", "_ASSIGNMENT_LOST", "REBALANCE_IN_PROGRESS", "ILLEGAL_GENERATION",
        "UNKNOWN_MEMBER_ID", "NOT_COORDINATOR", "COORDINATOR_NOT_AVAILABLE",
        "COORDINATOR_LOAD_IN_PROGRESS", "REQUEST_TIMED_OUT",
        "NOT_ENOUGH_REPLICAS", "NOT_ENOUGH_REPLICAS_AFTER_APPEND",
    )
}


def is_retryable_io(error):
    if isinstance(error, (RetryableIOError, ConnectionFailure, ExecutionTimeout, WTimeoutError)):
        return True
    if isinstance(error, KafkaException) and error.args:
        kafka_error = error.args[0]
        return isinstance(kafka_error, KafkaError) and not kafka_error.fatal() and (
            kafka_error.retriable() or kafka_error.code() in _RECOVERABLE_KAFKA_CODES
        )
    if isinstance(error, PyMongoError):
        return error.has_error_label("RetryableWriteError") or error.has_error_label("RetryableReadError")
    return False


class DataError(Exception):
    """Safe data error: details contain field names, never source values."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ResultConflict(RuntimeError):
    """Same parser version produced a different result; preserve the old result."""
