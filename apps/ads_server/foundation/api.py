"""foundation 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2)."""
from .access import owned_or_404, require_admin, require_advertiser
from .accounts import (
    AdvertiserAccount, ProfileView, change_password, create_advertiser, get_advertiser, list_advertisers, lock_user, profiles, set_advertiser_active,
    update_profile,
)
from .admin_site import ReadOnlyAdmin
from .dberrors import is_transient_lock_error, is_unique_violation
from .audit import latest_detail as latest_audit_detail, record_audit
from . import errors
from .http import json_depth, parse_json
from .models import AppendOnlyError, AppendOnlyModel, Role, User
from .net import client_ip
from .presentation import present
from .validators import MAX_AMOUNT, clean_request_key, clean_text, is_int, is_request_key, parse_uuid, parse_uuids

__all__ = [
    "present",  # 화면 데이터(설계 §6.6 "6-15 분리")
    "create_advertiser", "ProfileView", "update_profile", "change_password", "profiles", "AdvertiserAccount", "list_advertisers", "get_advertiser",
    "set_advertiser_active", "lock_user", "Role", "User", "client_ip",
    "owned_or_404", "require_admin", "require_advertiser", "is_unique_violation", "is_transient_lock_error", "json_depth", "parse_json",
    "errors", "record_audit", "latest_audit_detail", "MAX_AMOUNT", "AppendOnlyModel", "AppendOnlyError", "clean_text", "clean_request_key", "is_int", "is_request_key", "parse_uuid", "parse_uuids", "ReadOnlyAdmin",
]
