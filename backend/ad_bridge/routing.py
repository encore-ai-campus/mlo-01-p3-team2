"""발급 당시 슬롯으로 매체 키를 선택하여 조회·노출·재전송을 같은 매체에 보낸다."""

import os
from dataclasses import replace
from uuid import UUID

from .api.client import AdsClient


def _slot_id(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("광고 매체 연결의 슬롯 UUID를 확인해 주세요.") from None


class RoutedAdsClient:
    def __init__(self, config, *, environ=None):
        values = os.environ if environ is None else environ
        portal_key = values.get("ADS_PORTAL_MEDIA_KEY", "")
        slot_ids = values.get("ADS_PORTAL_MEDIA_SLOT_IDS", "")
        self._portal_slots = frozenset()
        self._portal = None
        if portal_key or slot_ids:
            if not portal_key or not slot_ids:
                raise ValueError("포털 매체 키와 해당 매체의 슬롯 목록을 함께 설정해 주세요.")
            parts = slot_ids.split(",")
            self._portal_slots = frozenset(_slot_id(part.strip()) for part in parts)
            # 현재 표시 슬롯과 과거 발급 슬롯의 키 연결을 별도로 유지한다.
            for name in ("ADS_PORTAL_LEFT_SLOT_ID", "ADS_PORTAL_RIGHT_SLOT_ID"):
                if values.get(name) and _slot_id(values[name]) not in self._portal_slots:
                    raise ValueError("현재 포털 슬롯이 포털 매체의 슬롯 목록에 없습니다.")
            roof = values.get("ADS_ROOFTOP_SLOT_ID")
            if roof and _slot_id(roof) in self._portal_slots:
                raise ValueError("옥상 슬롯은 기존 매체 키를 사용해야 합니다.")
            self._portal = AdsClient(replace(config, media_key=portal_key))
        self._default = AdsClient(config)

    def _for_slot(self, slot_id):
        return self._portal if _slot_id(slot_id) in self._portal_slots else self._default

    def _for_decision(self, decision_id):
        if self._portal is None:
            return self._default
        from .models import IssuedDecision

        # 현재 포털 설정이나 audience로 추측하지 않고 저장된 발급 슬롯을 읽는다.
        # 따라서 키 분리 이전의 개인 광고도 원래 매체로 보고·재전송한다.
        try:
            decision = IssuedDecision.objects.only("slot_id").get(pk=_slot_id(decision_id))
        except IssuedDecision.DoesNotExist:
            raise ValueError("매체를 확인할 광고 발급 기록이 없습니다.") from None
        return self._for_slot(decision.slot_id)

    def create_decision(self, *, slot_id, subject_id=None):
        return self._for_slot(slot_id).create_decision(slot_id=slot_id, subject_id=subject_id)

    def report_impression(self, *, decision_id, reaction_id, occurred_at, subject_id=None):
        return self._for_decision(decision_id).report_impression(
            decision_id=decision_id, reaction_id=reaction_id,
            occurred_at=occurred_at, subject_id=subject_id,
        )

    def get_reaction(self, *, decision_id, reaction_id):
        return self._for_decision(decision_id).get_reaction(
            decision_id=decision_id, reaction_id=reaction_id,
        )
