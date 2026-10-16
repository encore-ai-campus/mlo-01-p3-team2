"""외부 광고 서버 없이 사용하는 결정·접수 응답."""

from uuid import uuid4

from ad_bridge.api.types import Ad, Decision, Reaction


def shared_decision(*, ad=True):
    return Decision(
        decision_id=str(uuid4()), slot_id=str(uuid4()), slot_name="옥상 공유 슬롯",
        audience="shared", decided_at="2026-10-15T01:00:00Z", request_id="decision-request",
        ad=Ad(
            creative_id=str(uuid4()), title="테스트 광고",
            image_url="https://ads.example/assets/test.png",
            redirect_url="https://example.com/",
            click_url="https://ads.example/c/token?s={subject_id}",
        ) if ad else None,
    )


def received_reaction(**request):
    return Reaction(
        **request, type="IMPRESSION", received_at="2026-10-15T01:00:02Z",
        status="RECEIVED", reason_code=None, request_id="reaction-request",
    )
