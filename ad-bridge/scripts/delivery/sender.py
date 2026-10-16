"""최초 전송과 재전송에 동일한 전송·결과 저장 규칙을 적용한다."""

from dataclasses import dataclass
from datetime import timedelta

from ..api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ..impressions.store import StoredImpression
from .policy import RetryPolicy


@dataclass(frozen=True, slots=True)
class ImpressionReport:
    record: StoredImpression
    created: bool
    error: str | None = None
    upstream_status: int | None = None
    retry_after: int | None = None


def send_once(*, client, store, record: StoredImpression, policy: RetryPolicy, now) -> ImpressionReport:
    """커밋된 임대 하나를 전송한다. 오류 원문 대신 정해진 진단 코드만 저장한다."""

    try:
        reaction = client.report_impression(
            decision_id=record.decision_id, reaction_id=record.reaction_id,
            occurred_at=record.occurred_at, subject_id=record.subject_id,
        )
    except AdsHTTPError as error:
        uncertain = error.status == 429 or 500 <= error.status <= 599
        saved = store.finish_impression(
            record.reaction_id, delivery_state="UNCONFIRMED" if uncertain else "BLOCKED",
            request_id=error.request_id, lease_token=record.lease_token,
            next_attempt_at=(
                now() + timedelta(seconds=policy.delay_for(record.attempts, error.retry_after))
                if uncertain else None
            ),
            last_error="ads_http_error", last_http_status=error.status,
        )
        return ImpressionReport(saved, True, "ads_http_error", error.status, error.retry_after)
    except AdsTransportError:
        saved = store.finish_impression(
            record.reaction_id, delivery_state="UNCONFIRMED", lease_token=record.lease_token,
            next_attempt_at=now() + timedelta(seconds=policy.delay_for(record.attempts)),
            last_error="ads_unreachable",
        )
        return ImpressionReport(saved, True, "ads_unreachable")
    except AdsResponseError as error:
        # 2xx를 확인했다면 본문을 해석하지 못해도 미접수라고 단정하거나 PUT을 반복하지 않는다.
        saved = store.finish_impression(
            record.reaction_id,
            delivery_state="ACKNOWLEDGED" if error.acknowledged else "BLOCKED",
            request_id=error.request_id, lease_token=record.lease_token,
            last_error="ads_invalid_response",
        )
        return ImpressionReport(saved, True, "ads_invalid_response")
    except ValueError:
        # 호출 설정/저장 데이터가 잘못된 경우 원문에 포함될 수 있는 비밀값은 보관하지 않는다.
        saved = store.finish_impression(
            record.reaction_id, delivery_state="BLOCKED", lease_token=record.lease_token,
            last_error="ads_invalid_input",
        )
        return ImpressionReport(saved, True, "ads_invalid_input")

    # HTTP 완료 후 DB 쓰기가 실패하면 예외를 그대로 전파한다. 기존 예약은 이미 저장되어 있다.
    saved = store.finish_impression(
        record.reaction_id, delivery_state="ACKNOWLEDGED", status=reaction.status,
        reason_code=reaction.reason_code, request_id=reaction.request_id,
        lease_token=record.lease_token,
    )
    return ImpressionReport(saved, True)
