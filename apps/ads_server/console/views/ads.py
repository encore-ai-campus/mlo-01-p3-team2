"""광고 만들기(6-9d, 설계 §10 "광고 만들기 흐름" — Step 3 D3-3 을 대체): 이미 있는 캠페인을 고르고, 광고(광고그룹 + 입찰)와 소재(새로 올리기 또는
등록된 소재)를 **한 페이지 폼**으로 만든다. 저장은 원자적 `campaigns.create_ad` 하나다. 캠페인은 캠페인 목록에서 따로 만든다(끝나지 않은 캠페인이 없으면 안내만).

버튼 세 개가 같은 폼을 보낸다. 저장은 '집행'만 한다.
- 단위 적용: 고른 과금 단위의 게재 위치만 고를 수 있게 다시 그린다(JS 가 있으면 화면에서 바로 거른다 — `ad_create.js`).
- 미리보기: 입찰을 고른 위치마다 현재 정책에 대어 본 결과를 **서버가 계산**한다(JS 로 흉내 내지 않는다, D3-1). 입력은 막지 않는다.
- 집행: 만든다. 폼마다 새 요청 키를 실어, 두 번 누름·동시 제출·응답 실패 뒤 재시도도 하나만 만든다(키가 광고그룹 행에 저장된다).
"""
import secrets

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from campaigns import api as campaigns
from masters import api as masters

from ..errors import HANDLED, form_errors, message_of, status_of
from ..forms import EXISTING, NEW, AdCreateForm


def _render(request, form, choices, effects=None, status=200):
    names = {str(s.slot_id): f"{s.media_name} · {s.name}" for s in choices["slots"]}
    return render(request, "console/ad_create.html", {
        "form": form, "slots": choices["slots"], "unit": form["pricing_unit"].value(), "chosen": set(map(str, form["slot_ids"].value() or [])),
        "effects": [(names.get(str(e.slot_id), str(e.slot_id)), e) for e in effects] if effects else None,
        "max_bytes": settings.ASSET_MAX_BYTES, "has_creatives": bool(choices["creatives"]),
    }, status=status)


def _choices(user):
    """고를 수 있는 것: 끝나지 않은 캠페인(일시 중지·중단 포함), 켜진 게재 위치(매체 포함 — 단위가 다른 위치는 화면이 고를 수 없게 그린다), 내 소재."""
    return {
        "campaigns": [c for c in campaigns.list_campaigns(user) if c.status != campaigns.CampaignStatus.ENDED],
        "slots": masters.list_slots(active_only=True),
        "creatives": [owned.creative for owned in campaigns.list_owned_creatives(user)],
    }


def _form(choices, data=None, files=None, initial=None):
    return AdCreateForm(data, files, initial=initial, campaigns=choices["campaigns"], units=masters.PricingUnit.choices, slots=choices["slots"],
                        creatives=choices["creatives"])


def ad_create(request):
    choices = _choices(request.user)
    if not choices["campaigns"]:
        return render(request, "console/ad_create.html", {"no_campaign": True})
    if request.method != "POST":
        unit, campaign = request.GET.get("unit"), request.GET.get("campaign")
        initial = {"pricing_unit": unit if unit in masters.PricingUnit.values else None, "creative_source": NEW, "request_key": secrets.token_urlsafe(16),
                   "campaign_id": campaign if campaign in {str(c.campaign_id) for c in choices["campaigns"]} else None}
        return _render(request, _form(choices, initial=initial), choices)
    if not request.POST.get("request_key"):
        messages.warning(request, "화면이 오래됐거나 올바르지 않은 요청입니다. 새로 불러와 다시 만드세요.")
        return redirect("ad_create")
    action = request.POST.get("action")
    if action not in ("unit", "preview"):
        # 이미 성공한 제출의 다시 보냄은 폼 검증보다 먼저 처음 결과로 보낸다 — 그 사이 위치가 꺼지거나 상한에 닿아도(외부 검토 41d2288)
        try:
            done = campaigns.ad_created_by_key(request.user, request.POST["request_key"])
        except HANDLED as e:
            messages.error(request, message_of(e))
            return redirect("ad_create")
        if done is not None:
            messages.success(request, "이미 만든 광고입니다(같은 화면을 다시 보내도 하나만 만듭니다).")
            return redirect("ad_group_detail", ad_group_id=done.ad_group.ad_group_id)
    form = _form(choices, request.POST, request.FILES)
    if action in ("unit", "preview"):
        form.is_valid()  # 맞는 칸만 cleaned_data 에 남긴다
        form.errors.clear()  # 저장하지 않는 동작이라 빈 칸·이미지 등의 오류는 보이지 않는다
        return _render(request, form, choices, effects=_preview(form) if action == "preview" else None)
    status = 400
    if form.is_valid():
        d = form.cleaned_data
        if d["creative_source"] == EXISTING:
            creative = {"creative_id": d["creative_id"]}
        else:
            creative = {"creative": {"title": d["title"], "redirect_url": d["redirect_url"], "image_file": d["image"]}}
        try:
            created = campaigns.create_ad(
                request.user, d["campaign_id"],
                ad_group={"name": d["group_name"], "pricing_unit": d["pricing_unit"], "slot_ids": d["slot_ids"], "bid_amount": d["bid_amount"]},
                request_key=d["request_key"], **creative,
            )
        except HANDLED as e:
            form_errors(form, e, pointers=AdCreateForm.POINTERS, image_field="image")
            status = status_of(e)
        else:
            messages.success(request, "이미 만든 광고입니다(같은 화면을 다시 보내도 하나만 만듭니다)." if created.duplicate
                             else "광고를 만들었습니다. 승인 없이 바로 집행됩니다.")
            return redirect("ad_group_detail", ad_group_id=created.ad_group.ad_group_id)
    return _render(request, form, choices, status=status)


def _preview(form):
    """위치별 적용 결과(서버 계산). 입찰이나 위치가 없으면 안내만."""
    amount, slot_ids = form.cleaned_data.get("bid_amount"), form.cleaned_data.get("slot_ids")
    if amount is None or not slot_ids:
        form.add_error(None, "입찰과 게재 위치를 고르면 위치마다 노출 여부와 적용 금액을 보여 줍니다.")
        return None
    try:
        return campaigns.bid_effects(amount, slot_ids)
    except HANDLED as e:
        form_errors(form, e, pointers={"/bid_amount": "bid_amount"})
        return None
