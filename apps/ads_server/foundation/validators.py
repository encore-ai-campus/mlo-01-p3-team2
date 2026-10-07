"""계정 입력 규칙. 규칙은 **여기에만** 둔다(폼은 입력 변환만 한다, 설계 §6.6)."""
import re
import unicodedata

from django.core.exceptions import ValidationError

USERNAME_RE = re.compile(r"[a-z0-9_]{4,20}")


def validate_username(value):
    if not USERNAME_RE.fullmatch(value or ""):
        raise ValidationError("아이디는 영문 소문자·숫자·밑줄(_) 4~20자여야 합니다.", code="invalid_username")
    return value


def _has_control_or_format_chars(value):
    # 제어 문자와 보이지 않는 서식 문자(제로폭 공백 등)를 막는다.
    return any(unicodedata.category(ch).startswith("C") for ch in value)


def _clean_text(value, label, min_len, max_len):
    value = unicodedata.normalize("NFC", (value or "").strip())
    if _has_control_or_format_chars(value):
        raise ValidationError(f"{label}에 사용할 수 없는 문자가 있습니다.", code="invalid_chars")
    if not (min_len <= len(value) <= max_len):
        raise ValidationError(f"{label}은(는) {min_len}~{max_len}자여야 합니다.", code="invalid_length")
    return value


def clean_nickname(value):
    return _clean_text(value, "닉네임", 2, 20)


def clean_class_label(value):
    return _clean_text(value, "반", 1, 30)
