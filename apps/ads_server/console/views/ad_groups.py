"""광고그룹 상세(Step 3-2d): 위치별 결과, 입찰 이력과 새 입찰(낙관적 잠금), 이름·위치·켜기/끄기, 소재(미리보기·제목/주소 수정·켜기/끄기·이미지 교체).

동작마다 작은 폼을 따로 둔다 — 한 칸을 바꾸는 제출이 다른 칸을 옛 값으로 덮지 않는다(소재의 제목·주소는 한 폼이라 화면이 본 변경 시각과 대조한다).
뷰는 서비스를 부르고 그리기만 한다. 과금 단위는 바꿀 수 없고, 입찰은 추가만 된다(서비스 규칙).
"""
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from assets.api import asset_exists, content_type, open_asset
from campaigns import api as campaigns

from ..errors import HANDLED, fetch, form_errors, message_of, status_of
from ..forms import BidForm, CreativeEditForm, GroupNameForm, GroupSlotsForm, ImageForm
from ..queries.ad_groups import ad_group_page


def _page(request, ad_group_id, status=200, edit=None, **bound):
    """상세 화면. `bound` 는 오류와 함께 다시 그릴 폼, `edit` 는 (소재 ID, 다시 그릴 소재 수정 폼)."""
    page = fetch(ad_group_page, request.user, ad_group_id)
    group = page.group
    forms = {
        "bid_form": BidForm(initial={"expected_version": group.current_bid.bid_version if group.current_bid else None}),
        "name_form": GroupNameForm(initial={"name": group.name}),
        "slots_form": GroupSlotsForm(slots=page.choices, initial={"slot_ids": [str(s) for s in group.slot_ids]}),
        "image_form": ImageForm(),
        **bound,
    }
    edits = {c.creative_id: _edit_form(c) for c in page.creatives}
    if edit is not None:
        edits[edit[0]] = edit[1]
    return render(request, "console/ad_group_detail.html", {
        "page": page, "group": group, "effects": [(page.linked.get(e.slot_id), e) for e in page.effects],
        "creatives": [(c, edits[c.creative_id]) for c in page.creatives], **forms,
    }, status=status)


def _edit_form(creative, data=None):
    initial = {"title": creative.title, "redirect_url": creative.redirect_url, "updated_at": creative.updated_at.isoformat()}
    return CreativeEditForm(data, prefix=str(creative.creative_id), initial=initial)


def ad_group_detail(request, ad_group_id):
    return _page(request, ad_group_id)


def _done(request, ad_group_id, message):
    messages.success(request, message)
    return redirect("ad_group_detail", ad_group_id=ad_group_id)


@require_POST
def ad_group_bid(request, ad_group_id):
    form = BidForm(request.POST)
    if form.is_valid():
        try:
            campaigns.add_bid(request.user, ad_group_id, form.cleaned_data["amount"], form.cleaned_data["expected_version"])
        except HANDLED as e:
            form_errors(form, e, pointers={"/amount": "amount"})
            return _page(request, ad_group_id, status=status_of(e), bid_form=form)
        return _done(request, ad_group_id, "새 입찰을 넣었습니다. 위치별 결과가 바뀌었을 수 있습니다.")
    return _page(request, ad_group_id, status=400, bid_form=form)


@require_POST
def ad_group_name(request, ad_group_id):
    form = GroupNameForm(request.POST)
    if form.is_valid():
        try:
            campaigns.update_ad_group(request.user, ad_group_id, {"name": form.cleaned_data["name"]})
        except HANDLED as e:
            form_errors(form, e)
            return _page(request, ad_group_id, status=status_of(e), name_form=form)
        return _done(request, ad_group_id, "이름을 바꿨습니다.")
    return _page(request, ad_group_id, status=400, name_form=form)


@require_POST
def ad_group_slots(request, ad_group_id):
    page = fetch(ad_group_page, request.user, ad_group_id)
    form = GroupSlotsForm(request.POST, slots=page.choices)
    if form.is_valid():
        try:
            campaigns.update_ad_group(request.user, ad_group_id, {"slot_ids": form.cleaned_data["slot_ids"]})
        except HANDLED as e:
            form_errors(form, e)
            return _page(request, ad_group_id, status=status_of(e), slots_form=form)
        return _done(request, ad_group_id, "게재 위치를 바꿨습니다.")
    return _page(request, ad_group_id, status=400, slots_form=form)


@require_POST
def ad_group_enabled(request, ad_group_id):
    enabled = request.POST.get("enabled") == "1"
    try:
        campaigns.update_ad_group(request.user, ad_group_id, {"enabled": enabled})
    except HANDLED as e:
        messages.error(request, message_of(e))
        return redirect("ad_group_detail", ad_group_id=ad_group_id)
    return _done(request, ad_group_id, "광고그룹을 켰습니다." if enabled else "광고그룹을 껐습니다.")


def _creative_group(request, creative_id):
    return fetch(campaigns.get_creative, request.user, creative_id).ad_group_id  # 남의 소재는 404


@require_POST
def creative_edit(request, creative_id):
    current = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    group_id = current.ad_group_id
    form = _edit_form(current, request.POST)
    if form.is_valid():
        changes = {name: form.cleaned_data[name] for name in CreativeEditForm.EDITABLE if name in form.changed_data}
        if not changes:
            messages.info(request, "바뀐 것이 없습니다.")
            return redirect("ad_group_detail", ad_group_id=group_id)
        try:
            campaigns.update_creative(request.user, creative_id, changes, expected_updated_at=form.cleaned_data["updated_at"])
        except HANDLED as e:
            form_errors(form, e)
            return _page(request, group_id, status=status_of(e), edit=(current.creative_id, form))
        return _done(request, group_id, "소재를 수정했습니다.")
    return _page(request, group_id, status=400, edit=(current.creative_id, form))


@require_POST
def creative_enabled(request, creative_id):
    group_id = _creative_group(request, creative_id)
    enabled = request.POST.get("enabled") == "1"
    try:
        campaigns.update_creative(request.user, creative_id, {"enabled": enabled})
    except HANDLED as e:
        messages.error(request, message_of(e))
        return redirect("ad_group_detail", ad_group_id=group_id)
    return _done(request, group_id, "소재를 켰습니다." if enabled else "소재를 껐습니다.")


@require_POST
def creative_image(request, creative_id):
    group_id = _creative_group(request, creative_id)
    form = ImageForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            campaigns.replace_creative_image(request.user, creative_id, form.cleaned_data["image"])
        except HANDLED as e:
            form_errors(form, e, image_field="image")
            return _page(request, group_id, status=status_of(e), image_form=form)
        return _done(request, group_id, "이미지를 바꿨습니다. 이전 이미지는 이미 나간 광고를 위해 보관합니다.")
    return _page(request, group_id, status=400, image_form=form)


@require_safe
def creative_image_file(request, creative_id):
    """광고주 본인 소재의 현재 이미지(계획 S4). 공개 경로(`/assets/…`)는 중단·종료 캠페인의 이미지를 막지만, 광고주는 자기 소재를 계속 봐야 한다.
    소유를 확인한 뒤에만 내려 주고(남의 것·익명은 404), 공개 경로와 같은 `nosniff` 에 캐시는 남기지 않는다(기본 `no-store`)."""
    creative = fetch(campaigns.get_creative, request.user, creative_id)
    if not asset_exists(creative.image_name):
        raise Http404
    return FileResponse(open_asset(creative.image_name), content_type=content_type(creative.image_name))
