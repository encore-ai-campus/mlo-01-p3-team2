"""클릭 관측(C1 v1.1 `GET /c/{token}`, 설계 §10 "클릭 출처").

결정 응답의 `ad.click_url` 이 이 주소다. 토큰은 Django `signing` 으로 서명한 `decision_id` 뿐이다 — 위조·변조하면 무효(404)이고,
**유효 기간은 없다**(기간 규칙은 판정 단계가 한다). 이동할 곳은 요청이 아니라 결정에 저장된 `redirect_url` 이다.
**`subject_id` 를 토큰에 싣지 않는다**: `signing` 은 암호화가 아니라 base64 라서 가명 ID 가 URL(브라우저 기록·접근 로그)에 드러난다. 개인 슬롯의 사람은
결정(추가만 되는 기록, 사람 한 명)에서 정해진다.
"""
import logging
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core import signing
from django.db import OperationalError
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_GET

from foundation.api import errors
from masters import api as masters
from records import api as records

from .requests import UUID_PATTERN

logger = logging.getLogger(__name__)
SALT = "ads_server.click.v1"
MAX_TOKEN_LENGTH = 512  # 계약 `token` 의 maxLength
SHARED_TEMPLATE = "{subject_id}"  # 일괄 슬롯의 `click_url` 에서 매체가 사람의 `subject_id` 로 바꿔 넣는 자리


def make_click_url(decision):
    """`records.DecisionView`(광고가 있는 것) → 결정 응답에 싣는 `click_url`. 일괄 슬롯은 매체가 사람을 채울 `?s=` 자리가 남는다."""
    token = signing.dumps({"d": str(decision.decision_id)}, salt=SALT, compress=False)
    url = f"{settings.ASSET_PUBLIC_BASE_URL.rstrip('/')}/c/{token}"  # 공개 주소는 이미지(C3)와 같다
    return url if decision.audience == masters.Audience.INDIVIDUAL else f"{url}?s={SHARED_TEMPLATE}"


def parse_token(token):
    """서명이 맞는 토큰의 `decision_id`. 아니면 `NotFound`(왜 틀렸는지 알리지 않는다)."""
    if len(token) > MAX_TOKEN_LENGTH:
        raise errors.NotFound("찾을 수 없습니다.")
    try:
        payload = signing.loads(token, salt=SALT, max_age=None)
        decision_id = payload["d"]
        if not (isinstance(decision_id, str) and UUID_PATTERN.fullmatch(decision_id)):
            raise ValueError
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise errors.NotFound("찾을 수 없습니다.")
    return decision_id


def _viewer(request):
    """일괄 슬롯에서 클릭한 사람(`?s=`). UUID 가 아니면 없는 것과 같다(이동만 한다)."""
    value = request.GET.get("s", "")
    return str(uuid.UUID(value)) if UUID_PATTERN.fullmatch(value) else None


@login_not_required  # 최종 사용자 브라우저가 연다. 인증도 세션도 없어 쿠키를 만들지 않는다
@require_GET  # HEAD 는 받지 않는다: 링크 미리보기·프리페치가 클릭으로 기록되는 폭을 줄인다
def follow_click(request, token):
    decision_id = parse_token(token)
    try:
        url = records.observe_click(decision_id, _viewer(request))
    except OperationalError as error:  # 이동할 곳을 읽지 못했다. 복구되면 같은 주소를 다시 열면 된다
        # 원인을 한 줄로 남긴다(트레이스백 없음 — 장애 중에 클릭마다 트레이스백이 쌓이지 않게, 6-3b)
        logger.warning("클릭 처리 중 DB 오류로 503 decision=%s %s %s", decision_id, type(error).__name__, error.args[0] if error.args else "-")
        raise errors.Unavailable("일시적으로 처리할 수 없습니다. 잠시 뒤에 다시 시도하세요.")
    response = HttpResponseRedirect(url)  # 302
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
