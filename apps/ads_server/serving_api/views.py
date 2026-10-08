"""C1 엔드포인트(결정). 뷰는 얇다: 인증·요청 제한(`media_endpoint`) → 본문 검증 → `records` 호출 → 계약 모양으로 변환.

`slot_name` 은 표시용이라 결정에 저장하지 않고 응답을 만들 때 `masters` 에서 붙인다(DRD D-3).
"""
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from foundation.api import errors, parse_json
from masters import api as masters
from records import api as records

from .auth import media_endpoint
from .requests import UUID_PATTERN, parse_decision_request, parse_reaction_request, path_uuid

BASE = "/api/media/v1"


def _utc(moment, timespec="milliseconds"):
    return moment.isoformat(timespec=timespec).replace("+00:00", "Z")  # 계약: RFC 3339 UTC(`Z`)


def _reaction_body(reaction):
    return {
        "reaction_id": str(reaction.reaction_id), "decision_id": str(reaction.decision_id), "type": reaction.type,
        "occurred_at": _utc(reaction.occurred_at, "auto"),  # 매체가 보낸 정밀도를 잃지 않는다
        "received_at": _utc(reaction.received_at),
        "status": reaction.status, "reason_code": reaction.reason_code,
    }


def _decision_body(decision):
    ad = None
    if decision.chosen is not None:
        c = decision.chosen
        ad = {"creative_id": str(c.creative_id), "title": c.title, "image_url": c.image_url, "redirect_url": c.redirect_url}
    return {
        "decision_id": str(decision.decision_id), "slot_id": str(decision.slot_id),
        "slot_name": masters.slot_names([decision.slot_id]).get(decision.slot_id, ""),
        "audience": decision.audience, "decided_at": _utc(decision.decided_at), "ad": ad,
    }


@login_not_required
@require_GET
def health(request):
    """살아 있는지만 답한다(인증 없음). 저장소를 건드리지 않고 내부 정보를 싣지 않는다."""
    return JsonResponse({"status": "ok"})


@require_http_methods(["POST"])
@media_endpoint("decisions")
def create_decision(request):
    fields = parse_decision_request(parse_json(request))
    with transaction.atomic():  # 응답에 필요한 조회까지 한 트랜잭션: 어느 단계가 실패해도 503 은 "저장하지 않았다"는 뜻이다(계약 Unavailable)
        decision = records.decide(request.media.media_id, fields.slot_id, subject_id=fields.subject_id, context=fields.context)
        body = _decision_body(decision)
    response = JsonResponse(body, status=201)  # 커밋된 뒤에만 여기에 온다
    response["Location"] = f"{BASE}/decisions/{decision.decision_id}"
    return response


@require_http_methods(["GET"])
@media_endpoint("reads")
def get_decision(request, decision_id):
    if not UUID_PATTERN.fullmatch(decision_id):  # 계약 `Uuid` 형식만 받는다. 아닌 표기는 '없는 것'과 같다(records 와 같은 404)
        raise errors.NotFound("결정을 찾을 수 없습니다.")
    return JsonResponse(_decision_body(records.get_decision(request.media.media_id, decision_id)))


@media_endpoint("reactions")
def put_reaction(request, decision_id, reaction_id):
    decision_id, reaction_id = path_uuid(decision_id, "decision_id"), path_uuid(reaction_id, "reaction_id")
    body = parse_json(request)
    fields = parse_reaction_request(body)
    with transaction.atomic():  # 커밋된 뒤에만 2xx 를 보낸다: 2xx 는 "수신함에 저장했다"는 확인이다(커밋이 실패해도 503)
        reaction, created = records.receive_reaction(
            request.media.media_id, decision_id, reaction_id, fields.type, fields.occurred_at, raw=body,
        )
        payload = _reaction_body(reaction)
    if created:
        records.process_after_receipt(reaction.inbox_id)  # 커밋 뒤 한 번 바로 처리해 본다. 접수 응답(위 스냅샷)은 어떤 경우에도 바뀌지 않는다
    return JsonResponse(payload, status=201 if created else 200)


@media_endpoint("reads")
def get_reaction(request, decision_id, reaction_id):
    if not (UUID_PATTERN.fullmatch(decision_id) and UUID_PATTERN.fullmatch(reaction_id)):
        raise errors.NotFound("반응을 찾을 수 없습니다.")
    return JsonResponse(_reaction_body(records.get_reaction(request.media.media_id, decision_id, reaction_id)))


@login_not_required  # 인증은 아래 두 뷰의 `media_endpoint` 가 한다(경로군이 PUT 은 reactions, GET 은 reads 로 다르다)
@require_http_methods(["GET", "PUT"])
def reaction(request, decision_id, reaction_id):
    return (put_reaction if request.method == "PUT" else get_reaction)(request, decision_id, reaction_id)
