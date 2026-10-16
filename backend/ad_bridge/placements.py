"""옥상 공통 회차와 서버가 승인한 포털 이동의 광고를 발급·보관한다."""

from dataclasses import asdict
from datetime import datetime, timezone as utc, timedelta
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.utils import timezone

from .api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from .decisions.service import create_decision
from .decisions import store

ROUND_SECONDS = 10
TRANSFER_SALT = "ad-bridge.portal.v1"


def transfer_token(user_id, transfer_id):
    return signing.dumps({"user": str(user_id), "transfer": str(transfer_id)}, salt=TRANSFER_SALT)


def transfer_identity(token, user_id):
    data = signing.loads(token, salt=TRANSFER_SALT, max_age=15)
    if data.get("user") != str(user_id):
        raise signing.BadSignature("다른 사용자의 이동입니다.")
    return str(UUID(data["transfer"]))


def get_batch(*, client, owner_id, subject_id, transfer_id=None, now=None):
    from .models import PlacementBatch

    now = now or timezone.now()
    shared = transfer_id is None
    if shared:
        epoch = int(now.timestamp()) // ROUND_SECONDS * ROUND_SECONDS
        key = f"roof:{epoch}"
        expires = datetime.fromtimestamp(epoch + ROUND_SECONDS, tz=utc.utc)
        slots = [getattr(settings, "ADS_ROOFTOP_SLOT_ID", "")]
    else:
        key = f"portal:{transfer_id}"
        expires = now + timedelta(seconds=15)
        slots = [getattr(settings, name, "") for name in ("ADS_PORTAL_LEFT_SLOT_ID", "ADS_PORTAL_RIGHT_SLOT_ID")]
    # 모든 슬롯을 발급 전에 검증해 부분 설정으로 외부 결정을 낭비하지 않는다.
    slots = [str(UUID(slot)) for slot in slots]
    batch, created = PlacementBatch.objects.get_or_create(
        key=key, defaults={"owner_id": None if shared else owner_id, "expires_at": expires},
    )
    if not shared and batch.owner_id != owner_id:
        raise ValueError("이동 소유자가 일치하지 않습니다.")
    if created:
        payload = []
        try:
            for slot in slots:
                decision = create_decision(client=client, store=store, slot_id=slot,
                    owner_id=None if shared else owner_id, subject_id=None if shared else subject_id)
                item = asdict(decision)
                # 같은 소재는 결정과 클릭 URL까지 통일하여 별도 결정의 선행 노출 누락을 막는다.
                canonical = next((old for old in payload if old["ad"] and item["ad"]
                                  and old["ad"]["creative_id"] == item["ad"]["creative_id"]), None)
                payload.append(canonical or item)
        except (AdsHTTPError, AdsResponseError, AdsTransportError, ValueError):
            # POST 결과 유실은 발급 여부가 불명확하다. 같은 회차·이동에서 자동 재발급하지 않는다.
            batch.state = "FAILED"
        else:
            batch.state = "READY"
            batch.payload = payload
        batch.save(update_fields=["state", "payload"])
    return batch


def public_batch(batch, subject_id):
    ads = []
    for entry in batch.payload:
        ad = entry["ad"]
        ads.append({"decision_id": entry["decision_id"], "ad": None if ad is None else {
            "creative_id": ad["creative_id"], "title": ad["title"], "image_url": ad["image_url"],
            "click_url": ad["click_url"].replace("{subject_id}", str(subject_id)),
        }})
    return {"batch_id": batch.key, "state": batch.state, "ads": ads,
            "server_time": timezone.now().isoformat(), "expires_at": batch.expires_at.isoformat()}
