"""feat;#17 게임의 로그인 프로필과 기존 광고 요청 모듈을 연결한다."""

import hashlib
import hmac
from datetime import timezone as utc_timezone
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from ..api.client import AdsClient
from ..api.config import AdsConfig
from ..api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ..decisions import store as decision_store
from ..decisions.service import create_decision
from ..impressions import store as impression_store
from ..impressions.service import report_impression_once
from ..results.service import refresh_result


@transaction.non_atomic_requests
@never_cache
@login_required
@require_POST
def request_decision(request):
    """개인 슬롯 요청 한 번. Django 기본 CSRF 미들웨어와 함께 사용한다."""
    slot_id = getattr(settings, "ADS_SLOT_ID", "")
    if not slot_id:
        return JsonResponse({
            "error": "ads_not_configured", "message": "게임 서버의 ADS_SLOT_ID를 설정해 주세요.",
        }, status=503)
    if not apps.is_installed("ad_bridge"):
        return JsonResponse({
            "error": "ads_storage_not_configured", "message": "ad_bridge 앱 등록과 마이그레이션이 필요합니다.",
        }, status=503)

    try:
        config = AdsConfig.from_env()
        # 브라우저 입력 대신 로그인 프로필과 서버 전용 비밀로 광고 가명을 만든다.
        owner_id = _owner_id(request.user)
        if owner_id is None:
            return JsonResponse({
                "error": "profile_uuid_missing", "message": "게임 프로필의 사용자 UUID가 없습니다.",
            }, status=409)
        client = AdsClient(config)
        subject_id = _subject_id(owner_id, subject_secret=config.subject_secret)
        decision = create_decision(
            client=client, store=decision_store, slot_id=slot_id,
            subject_id=subject_id, owner_id=owner_id,
        )
    except DatabaseError:
        return JsonResponse({
            "error": "ads_storage_unavailable", "message": "광고 발급 기록을 저장하지 못했습니다.",
        }, status=503)
    except ValueError:
        return JsonResponse({
            "error": "ads_invalid_config",
            "message": "광고 API 주소·매체 키·타임아웃·가명 비밀·슬롯 및 사용자 UUID 설정을 확인해 주세요.",
        }, status=503)
    except AdsHTTPError as error:
        return JsonResponse({
            "error": "ads_http_error", "message": f"광고 서버 응답: HTTP {error.status}",
            "upstream_status": error.status, "request_id": error.request_id,
        }, status=502)
    except AdsTransportError:
        return JsonResponse({
            "error": "ads_unreachable", "message": "광고 서버 연결 실패 또는 시간 초과입니다.",
        }, status=502)
    except AdsResponseError:
        return JsonResponse({
            "error": "ads_invalid_response", "message": "광고 서버의 응답 형식이 올바르지 않습니다.",
        }, status=502)

    # 공개 광고 필드만 전달한다. 매체 키·프로필 UUID·원본 오류 본문은 반환하지 않는다.
    ad = decision.ad
    return JsonResponse({
        "decision_id": decision.decision_id,
        "slot_id": decision.slot_id,
        "audience": decision.audience,
        "decided_at": decision.decided_at,
        "request_id": decision.request_id,
        "ad": None if ad is None else {
            "creative_id": ad.creative_id, "title": ad.title,
            "image_url": ad.image_url, "click_url": ad.click_url,
        },
    }, status=201)


@transaction.non_atomic_requests
@never_cache
@login_required
@require_POST
def report_impression(request, decision_id):
    """개인 슬롯의 노출 알림을 최초 한 번 보고한다. 실제 화면 감지는 호출자의 책임이다."""
    if not apps.is_installed("ad_bridge"):
        return JsonResponse({
            "error": "ads_storage_not_configured", "message": "ad_bridge 앱 등록과 마이그레이션이 필요합니다.",
        }, status=503)
    try:
        config = AdsConfig.from_env()
        owner_id = _owner_id(request.user)
        if owner_id is None:
            return JsonResponse({
                "error": "profile_uuid_missing", "message": "게임 프로필의 사용자 UUID가 없습니다.",
            }, status=409)
        client = AdsClient(config)
        # 브라우저의 사용자·반응 ID·과거 시각을 쓰지 않고 서버가 알림을 확인한 시각을 고정한다.
        occurred_at = timezone.now().astimezone(utc_timezone.utc).isoformat().replace("+00:00", "Z")
        outcome = report_impression_once(
            client=client, store=impression_store, decision_id=decision_id,
            owner_id=owner_id, occurred_at=occurred_at,
        )
    except impression_store.DecisionNotFound:
        return JsonResponse({
            "error": "decision_not_found", "message": "이 사용자에게 발급한 광고 결정을 찾을 수 없습니다.",
        }, status=404)
    except impression_store.NoAdForDecision:
        return JsonResponse({
            "error": "no_ad_to_report", "message": "광고가 없는 결정은 노출 보고할 수 없습니다.",
        }, status=409)
    except ValueError:
        return JsonResponse({
            "error": "ads_invalid_config", "message": "광고 설정 또는 게임 사용자 UUID를 확인해 주세요.",
        }, status=503)
    except DatabaseError:
        # 전송 후 저장 실패일 수도 있다. 미접수라고 단정하거나 새로운 반응을 만들지 않는다.
        return JsonResponse({
            "error": "ads_storage_unavailable",
            "message": "노출 기록을 확인하지 못했습니다. 광고 서버 접수 여부는 확정할 수 없습니다.",
        }, status=503)

    record = outcome.record
    payload = {
        "decision_id": record.decision_id, "reaction_id": record.reaction_id,
        "occurred_at": record.occurred_at, "delivery_state": record.delivery_state,
        "status": record.status, "reason_code": record.reason_code,
        "request_id": record.request_id, "duplicate": not outcome.created,
    }
    if outcome.error:
        payload["error"] = outcome.error
    if outcome.upstream_status is not None:
        payload["upstream_status"] = outcome.upstream_status
    if outcome.retry_after is not None:
        payload["retry_after"] = outcome.retry_after

    if record.delivery_state == "ACKNOWLEDGED":
        # 201/200은 접수 확인이며 인정·과금 완료가 아니다. 본문 미확인 상태도 분리한다.
        response_status = (201 if outcome.created else 200) if record.status else 202
    elif outcome.error or record.delivery_state == "BLOCKED":
        response_status = 502
    else:
        response_status = 202
    return JsonResponse(payload, status=response_status)



def _owner_id(user) -> UUID | None:
    """로그인 프로필의 내부 소유자 UUID를 읽고 원문 없는 오류로 검증한다."""
    value = user
    for attribute in getattr(settings, "ADS_SUBJECT_ID_ATTRIBUTE", "campus_profile.user_uuid").split("."):
        value = getattr(value, attribute, None)
        if value is None:
            break
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("게임 프로필의 사용자 UUID가 올바르지 않습니다.") from None


def _subject_id(user_uuid: UUID, *, subject_secret: str) -> UUID:
    """검증된 내부 UUID에서 결정 발급에 사용할 광고 전용 가명을 생성한다."""
    # UUID 표기를 정규화하고 계약의 앞 16바이트를 그대로 사용한다. 버전 비트는 바꾸지 않는다.
    digest = hmac.new(
        subject_secret.encode("utf-8"),
        f"ads-subject/v1:{user_uuid}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return UUID(bytes=digest[:16])


def _result_payload(record):
    return {
        "decision_id": record.decision_id, "reaction_id": record.reaction_id,
        "delivery_state": record.delivery_state, "status": record.status,
        "reason_code": record.reason_code, "request_id": record.request_id,
        "attempts": record.attempts, "last_error": record.last_error,
    }


@transaction.non_atomic_requests
@never_cache
@login_required
@require_POST
def reaction_result(request, decision_id):
    """서버 저장 상태를 확인하고 접수된 반응만 광고 서버에서 한 번 조회한다."""
    if not apps.is_installed("ad_bridge"):
        return JsonResponse({"error": "ads_storage_not_configured", "message": "ad_bridge 앱 등록과 마이그레이션이 필요합니다."}, status=503)
    try:
        config = AdsConfig.from_env()
        owner_id = _owner_id(request.user)
        if owner_id is None:
            return JsonResponse({"error": "profile_uuid_missing", "message": "게임 사용자 UUID가 없습니다."}, status=409)
        record = impression_store.get_impression(decision_id=decision_id, owner_id=owner_id)
        # 재전송 대기 중에는 로컬 상태만 반환한다. 이미 확정된 판정도 재조회하지 않는다.
        if record.delivery_state != "ACKNOWLEDGED" or record.status in ("ACCEPTED", "REJECTED"):
            return JsonResponse(_result_payload(record), status=202 if record.delivery_state != "ACKNOWLEDGED" else 200)
        record = refresh_result(client=AdsClient(config), store=impression_store,
                                decision_id=decision_id, owner_id=owner_id)
        return JsonResponse(_result_payload(record))
    except impression_store.DecisionNotFound:
        return JsonResponse({"error": "decision_not_found", "message": "사용자의 노출 기록이 없습니다."}, status=404)
    except DatabaseError:
        return JsonResponse({"error": "ads_storage_unavailable", "message": "노출 기록을 확인하지 못했습니다."}, status=503)
    except ValueError:
        return JsonResponse({"error": "ads_invalid_config", "message": "광고 연결 설정을 확인해 주세요."}, status=503)
    except AdsHTTPError as error:
        response = JsonResponse({"error": "ads_http_error", "message": f"판정 조회 HTTP {error.status}",
                                 "upstream_status": error.status, "retry_after": error.retry_after}, status=502)
        if error.retry_after is not None:
            response["Retry-After"] = str(error.retry_after)
        return response
    except (AdsTransportError, AdsResponseError):
        return JsonResponse({"error": "ads_lookup_failed", "message": "판정 조회 실패. 기존 노출은 유지됩니다."}, status=502)
