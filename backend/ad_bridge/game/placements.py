"""로그인·CSRF를 유지하는 화면 광고 조회 API."""

import json
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from ..routing import RoutedAdsClient as AdsClient
from ..api.config import AdsConfig
from ..placements import get_batch, public_batch, transfer_identity
from .views import _owner_id, _subject_id


@transaction.non_atomic_requests
@never_cache
@login_required
@require_POST
def placement(request, location):
    if not getattr(settings, "ADS_ENABLED", False):
        return JsonResponse({"error": "ads_disabled"}, status=503)
    try:
        owner = _owner_id(request.user)
        if owner is None:
            return JsonResponse({"error": "profile_uuid_missing"}, status=409)
        transfer = None
        if location == "portal":
            body = json.loads(request.body)
            if not isinstance(body, dict) or not isinstance(body.get("token"), str) or len(body["token"]) > 2048:
                return JsonResponse({"error": "invalid_transfer"}, status=400)
            transfer = transfer_identity(body["token"], request.user.pk)
        elif location != "rooftop":
            return JsonResponse({"error": "unknown_placement"}, status=404)
        config = AdsConfig.from_env()
        subject = _subject_id(owner, subject_secret=config.subject_secret)
        batch = get_batch(client=AdsClient(config), owner_id=owner, subject_id=subject, transfer_id=transfer)
        return JsonResponse(public_batch(batch, subject), status=202 if batch.state == "PENDING" else 200)
    except (signing.BadSignature, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid_transfer"}, status=400)
    except (DatabaseError, ValueError):
        return JsonResponse({"error": "ads_unavailable"}, status=503)
