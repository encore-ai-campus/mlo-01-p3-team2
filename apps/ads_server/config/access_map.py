"""URL 접두사 → 역할 표. **접근 통제의 단일 출처**다.

새 URL 은 아래 접두사 밑에 추가하면 자동으로 보호된다. 역할 접두사 밖의 URL 은
공개(@login_not_required)이거나 "로그인만 필요"로 명시해야 하며, tests/test_access.py 의 URL 전수 점검이 이를 강제한다.
"""
from django.core.exceptions import ImproperlyConfigured

ADVERTISER_PREFIX = "/advertiser/"


def validate_admin_path(path, allow_default=False):
    """ADMIN_URL_PATH: 앞 슬래시 없이 `xxxx/` 형태. 기본값 `admin/` 은 prod 에서 금지."""
    if not path or path.startswith("/") or not path.endswith("/") or "//" in path:
        raise ImproperlyConfigured("ADMIN_URL_PATH 는 앞 슬래시 없이 `이름/` 형태여야 합니다.")
    if path == "admin/" and not allow_default:
        raise ImproperlyConfigured("ADMIN_URL_PATH 에 기본값 `admin/` 을 쓸 수 없습니다.")
    return path


def build_access_map(admin_path):
    """각 항목: prefix, role, hide.

    hide=True  → 그 역할이 아니면 **익명 포함 누구에게나 404**(존재를 숨긴다). 관리자 화면.
    hide=False → 익명은 통과시켜 로그인으로 보내고, 로그인했지만 역할이 다르면 403. 광고주 화면.
    """
    return [
        {"prefix": "/" + admin_path, "role": "admin", "hide": True},
        {"prefix": ADVERTISER_PREFIX, "role": "advertiser", "hide": False},
    ]
