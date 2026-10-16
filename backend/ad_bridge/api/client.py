"""C1 v1.1 결정 요청·노출 보고·판정 조회. 한 번만 전송하며 재전송·차감은 수행하지 않는다."""

import json
import re
from datetime import datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .config import AdsConfig
from .errors import AdsHTTPError, AdsResponseError, AdsTransportError
from .types import Ad, Decision, Reaction

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
_MAX_RESPONSE_BYTES = 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 인증 헤더가 다른 주소로 넘어가거나 POST·PUT의 의미가 바뀌는 것을 막는다.
        return None


def _uuid(value: str | UUID, field: str) -> str:
    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ValueError(f"{field}는 하이픈을 포함한 UUID여야 합니다.")
    return str(UUID(value))


def _utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ValueError(f"{field}는 Z로 끝나는 UTC 시각이어야 합니다.")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field}는 실제로 존재하는 UTC 시각이어야 합니다.") from None


def _url(value: str, *, https_only: bool = False) -> bool:
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in (("https",) if https_only else ("http", "https"))
                and bool(parsed.hostname) and parsed.username is None and parsed.password is None
                and (parsed.port is None or parsed.port > 0))
    except ValueError:
        return False


def _parse_decision(body: bytes, slot_id: str, audience: str, request_id: str | None) -> Decision:
    """필수 값만 읽고 추가된 응답 필드는 무시한다. 잘못된 응답은 광고 없음과 구분한다."""
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
        decision_id = _uuid(data["decision_id"], "decision_id")
        received_slot = _uuid(data["slot_id"], "slot_id")
        if received_slot != slot_id or data["audience"] != audience:
            raise ValueError
        if not isinstance(data["slot_name"], str):
            raise ValueError
        stamp = data["decided_at"]
        if not isinstance(stamp, str) or not _UTC.fullmatch(stamp):
            raise ValueError
        datetime.fromisoformat(stamp)  # 문법뿐 아니라 실제로 존재하는 날짜도 확인한다.
        raw_ad = data["ad"]
        ad = None
        if raw_ad is not None:
            if not isinstance(raw_ad, dict):
                raise ValueError
            creative_id = _uuid(raw_ad["creative_id"], "creative_id")
            if not isinstance(raw_ad["title"], str) or not 1 <= len(raw_ad["title"]) <= 200:
                raise ValueError
            for name in ("image_url", "redirect_url", "click_url"):
                value = raw_ad[name]
                if not isinstance(value, str) or not _url(value, https_only=name == "redirect_url"):
                    raise ValueError
            # shared의 click_url에는 {subject_id}가 포함될 수 있어 URI 템플릿을 그대로 보존한다.
            ad = Ad(creative_id, raw_ad["title"], raw_ad["image_url"], raw_ad["redirect_url"], raw_ad["click_url"])
        return Decision(decision_id, received_slot, data["slot_name"], data["audience"], stamp, ad, request_id)
    except (ValueError, KeyError, TypeError, RecursionError):
        raise AdsResponseError("광고 서버의 결정 응답이 계약 형식과 다릅니다.", request_id=request_id) from None


class AdsClient:
    def __init__(self, config: AdsConfig) -> None:
        self._config = config
        self._opener = build_opener(_NoRedirect())

    def _safe_metadata(self, value: str | None) -> str | None:
        # 잘못된 서버가 키를 응답 헤더·오류 코드에 반사하더라도 진단 정보에는 남기지 않는다.
        return value.replace(self._config.media_key, "[REDACTED]")[:256] if isinstance(value, str) else None

    def _http_error(self, response) -> AdsHTTPError:
        request_id = self._safe_metadata(response.headers.get("X-Request-ID"))
        raw_retry = response.headers.get("Retry-After", "")
        retry_after = int(raw_retry) if re.fullmatch(r"[0-9]{1,10}", raw_retry) else None
        code = None
        try:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) <= _MAX_RESPONSE_BYTES:
                problem = json.loads(raw)
                if isinstance(problem, dict):
                    code = self._safe_metadata(problem.get("code"))
        except (ValueError, RecursionError, OSError, HTTPException):
            pass  # HTML 오류 페이지나 손상된 본문이어도 HTTP 상태를 잃지 않는다.
        return AdsHTTPError(response.code, code=code, request_id=request_id, retry_after=retry_after)

    def create_decision(self, slot_id: str | UUID, subject_id: str | UUID | None = None) -> Decision:
        """개인 슬롯에는 가명 subject_id를 전달하고, shared 슬롯에서는 생략한다. 자동 재시도하지 않는다."""
        slot = _uuid(slot_id, "slot_id")
        payload = {"slot_id": slot}
        if subject_id is not None:
            payload["subject_id"] = _uuid(subject_id, "subject_id")
        audience = "shared" if subject_id is None else "individual"
        request = Request(
            f"{self._config.base_url}/decisions", method="POST",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"X-Media-Key": self._config.media_key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._config.timeout) as response:
                request_id = self._safe_metadata(response.headers.get("X-Request-ID"))
                if response.status != 201:
                    raise AdsResponseError("광고 결정 생성의 성공 상태는 HTTP 201이어야 합니다.", request_id=request_id)
                if response.headers.get_content_type() != "application/json":
                    raise AdsResponseError("광고 서버가 JSON 응답을 반환하지 않았습니다.", request_id=request_id)
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise AdsResponseError("광고 서버 응답이 1 MiB 제한을 넘었습니다.", request_id=request_id)
                return _parse_decision(body, slot, audience, request_id)
        except HTTPError as exc:
            with exc:
                error = self._http_error(exc)
            raise error from None
        except (URLError, OSError, HTTPException):
            # POST는 멱등하지 않으므로 연결 실패에도 여기서 다시 보내지 않는다.
            raise AdsTransportError("광고 서버 연결 또는 응답 수신에 실패했습니다. 결정 생성 여부는 확인할 수 없습니다.") from None

    def _parse_reaction(self, body: bytes, decision_id: str, reaction_id: str,
                        occurred_at: str | None, subject_id: str | None, request_id: str | None,
                        *, lookup: bool = False) -> Reaction:
        """보낸 반응과 일치하는 필수 값은 검증하고 새 필드·거부 사유는 허용한다."""
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError
            received_decision = _uuid(data["decision_id"], "decision_id")
            received_reaction = _uuid(data["reaction_id"], "reaction_id")
            raw_subject = data["subject_id"]
            received_subject = None if raw_subject is None else _uuid(raw_subject, "subject_id")
            if (received_decision != decision_id or received_reaction != reaction_id
                    or (not lookup and received_subject != subject_id) or data["type"] != "IMPRESSION"):
                raise ValueError
            # 서버가 .123을 .123000으로 표시해도 같은 UTC 시각이면 같은 반응이다.
            actual_time = _utc(data["occurred_at"], "occurred_at")
            if not lookup and actual_time != _utc(occurred_at, "occurred_at"):
                raise ValueError
            _utc(data["received_at"], "received_at")
            if data["status"] not in ("RECEIVED", "ACCEPTED", "REJECTED"):
                raise ValueError
            reason = data["reason_code"]
            if reason is not None and not isinstance(reason, str):
                raise ValueError
            if reason is not None:
                reason = reason.replace(self._config.media_key, "[REDACTED]")
            return Reaction(received_reaction, received_decision, received_subject, "IMPRESSION",
                            data["occurred_at"], data["received_at"], data["status"], reason, request_id)
        except (ValueError, KeyError, TypeError, RecursionError):
            raise AdsResponseError("광고 서버의 반응 응답이 계약 형식과 다릅니다.",
                                   request_id=request_id, acknowledged=not lookup) from None

    def report_impression(self, *, decision_id: str | UUID, reaction_id: str | UUID,
                          occurred_at: str, subject_id: str | UUID | None = None) -> Reaction:
        """호출자가 보관한 반응 ID·감지 시각으로 노출을 한 번 보고한다. 자동 재시도하지 않는다."""
        decision = _uuid(decision_id, "decision_id")
        reaction = _uuid(reaction_id, "reaction_id")
        _utc(occurred_at, "occurred_at")
        subject = None if subject_id is None else _uuid(subject_id, "subject_id")
        payload = {"type": "IMPRESSION", "occurred_at": occurred_at}
        if subject is not None:
            payload["subject_id"] = subject
        request = Request(
            f"{self._config.base_url}/decisions/{decision}/reactions/{reaction}", method="PUT",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"X-Media-Key": self._config.media_key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        acknowledged = False
        request_id = None
        try:
            with self._opener.open(request, timeout=self._config.timeout) as response:
                # 본문을 읽다가 실패해도 이미 받은 접수 성공(2xx)은 유지해야 한다.
                acknowledged = 200 <= response.status < 300
                request_id = self._safe_metadata(response.headers.get("X-Request-ID"))
                if response.status not in (200, 201):
                    raise AdsResponseError("반응 보고의 성공 상태는 HTTP 200 또는 201이어야 합니다.",
                                           request_id=request_id, acknowledged=acknowledged)
                if response.headers.get_content_type() != "application/json":
                    raise AdsResponseError("광고 서버가 JSON 응답을 반환하지 않았습니다.",
                                           request_id=request_id, acknowledged=True)
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise AdsResponseError("광고 서버 응답이 1 MiB 제한을 넘었습니다.",
                                           request_id=request_id, acknowledged=True)
                return self._parse_reaction(body, decision, reaction, occurred_at, subject, request_id)
        except HTTPError as exc:
            with exc:
                error = self._http_error(exc)
            raise error from None
        except (URLError, OSError, HTTPException):
            if acknowledged:
                raise AdsResponseError("노출은 접수됐지만 광고 서버의 응답 본문을 받지 못했습니다.",
                                       request_id=request_id, acknowledged=True) from None
            raise AdsTransportError("광고 서버 연결 또는 응답 수신에 실패했습니다. 노출 접수 여부는 확인할 수 없습니다.") from None


    def get_reaction(self, *, decision_id: str | UUID, reaction_id: str | UUID) -> Reaction:
        """저장된 노출 반응의 판정을 한 번 조회한다. PUT이나 자동 재시도는 하지 않는다."""
        decision = _uuid(decision_id, "decision_id")
        reaction = _uuid(reaction_id, "reaction_id")
        request = Request(
            f"{self._config.base_url}/decisions/{decision}/reactions/{reaction}", method="GET",
            headers={"X-Media-Key": self._config.media_key, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._config.timeout) as response:
                request_id = self._safe_metadata(response.headers.get("X-Request-ID"))
                if response.status != 200:
                    raise AdsResponseError("반응 조회의 성공 상태는 HTTP 200이어야 합니다.", request_id=request_id)
                if response.headers.get_content_type() != "application/json":
                    raise AdsResponseError("광고 서버가 JSON 응답을 반환하지 않았습니다.", request_id=request_id)
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise AdsResponseError("광고 서버 응답이 1 MiB 제한을 넘었습니다.", request_id=request_id)
                return self._parse_reaction(body, decision, reaction, None, None, request_id, lookup=True)
        except HTTPError as exc:
            with exc:
                error = self._http_error(exc)
            raise error from None
        except (URLError, OSError, HTTPException):
            raise AdsTransportError("광고 서버의 반응 조회에 실패했습니다.") from None
