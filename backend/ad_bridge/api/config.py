"""광고 API 연결 설정·가명 생성 비밀과 입력 검증."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class AdsConfig:
    """직접 주입하거나 from_env()로 생성하는 광고 통신 설정."""

    base_url: str
    media_key: str = field(repr=False)
    timeout: float
    subject_secret: str = field(repr=False, kw_only=True)

    def __post_init__(self) -> None:
        # URL 파서가 일부 제어 문자를 지우기 전에 잘못된 입력을 거부한다.
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise ValueError("ADS_API_BASE_URL이 필요합니다.")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.base_url):
            raise ValueError("ADS_API_BASE_URL에 제어 문자를 넣을 수 없습니다.")
        base_url = self.base_url.strip()
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and not any(char.isspace() for char in base_url)
                and "\\" not in base_url
                and parsed.username is None
                and parsed.password is None
                and "?" not in base_url
                and "#" not in base_url
                and parsed.path in {"/api/media/v1", "/api/media/v1/"}
                and (port is None or port > 0)
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError(
                "ADS_API_BASE_URL은 호스트와 /api/media/v1 경로를 포함한 "
                "HTTP(S) 주소여야 합니다. 사용자 정보·쿼리·프래그먼트는 허용하지 않습니다."
            )

        # 키의 값이나 잘못된 입력 원문을 오류 메시지에 포함하지 않는다.
        if not isinstance(self.media_key, str) or not self.media_key.strip():
            raise ValueError("ADS_MEDIA_KEY가 필요합니다.")
        if any(not 33 <= ord(char) <= 126 for char in self.media_key):
            raise ValueError("ADS_MEDIA_KEY에는 공백·제어 문자·비ASCII 문자를 넣을 수 없습니다.")

        # 비밀은 자동 보정하지 않는다. 잘못된 설정으로 다른 가명이 생성되는 것을 막는다.
        if not isinstance(self.subject_secret, str) or not self.subject_secret:
            raise ValueError("ADS_SUBJECT_SECRET이 필요합니다.")
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in self.subject_secret):
            raise ValueError("ADS_SUBJECT_SECRET에는 공백·제어 문자를 넣을 수 없습니다.")
        try:
            self.subject_secret.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("ADS_SUBJECT_SECRET은 UTF-8 문자열이어야 합니다.") from None

        try:
            if isinstance(self.timeout, bool):
                raise ValueError
            timeout = float(self.timeout)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("ADS_API_TIMEOUT은 초 단위의 유한한 양수여야 합니다.") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("ADS_API_TIMEOUT은 초 단위의 유한한 양수여야 합니다.")

        # 생성할 때만 정규화하고, 이후 설정은 변경하지 못하게 한다.
        object.__setattr__(self, "base_url", base_url.rstrip("/"))
        object.__setattr__(self, "timeout", timeout)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AdsConfig":
        """호출 시 환경변수를 읽는다. 테스트에서는 별도 매핑을 전달할 수 있다."""
        values = os.environ if environ is None else environ
        names = ("ADS_API_BASE_URL", "ADS_MEDIA_KEY", "ADS_API_TIMEOUT", "ADS_SUBJECT_SECRET")
        for name in names:
            value = values.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}이 필요합니다.")
        return cls(
            base_url=values["ADS_API_BASE_URL"],
            media_key=values["ADS_MEDIA_KEY"],
            timeout=values["ADS_API_TIMEOUT"],
            subject_secret=values["ADS_SUBJECT_SECRET"],
        )
