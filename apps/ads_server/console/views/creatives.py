"""소재 화면(6-9d, 설계 §10 "소재 목록"): 내 소재 목록(올리기·쓰는 광고·삭제), 소재 상세(제목/주소 수정·이미지 교체·삭제), 소재 이미지.

소재는 광고주 소유이고 여러 광고에 연결된다. 그래서 수정·이미지 교체 폼은 광고 상세와 소재 상세 두 곳에 있고, 폼의 숨김 칸 `ad_group_id` 가 있으면 그 광고 상세로,
없으면 소재 상세로 돌아온다. "삭제"는 보관이다 — 끝나지 않은 캠페인의 광고에 연결돼 있으면 서비스가 거절한다(409).
"""
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from assets.api import asset_exists, content_type, open_asset
from campaigns import api as campaigns

from ..errors import HANDLED, fetch, form_errors, run_action, status_of
from ..forms import CreativeEditForm, CreativeUploadForm
from .ad_groups import _edit_form, _image_form, _page as _ad_page


def creative_list(request):
    """내 소재(보관하지 않은 것)와 소재마다 쓰는 광고. 여기서 올린 소재는 아직 어느 광고에도 연결되지 않는다."""
    form = CreativeUploadForm(request.POST or None, request.FILES or None, prefix="new")
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            d = form.cleaned_data
            try:
                c = campaigns.create_creative(request.user, None, d["title"], d["redirect_url"], d["image"])
            except HANDLED as e:
                form_errors(form, e, image_field="image")
                status = status_of(e)
            else:
                messages.success(request, "소재를 올렸습니다. 광고 만들기나 광고 상세에서 이 소재를 쓸 수 있습니다.")
                return redirect("creative_detail", creative_id=c.creative_id)
    return render(request, "console/creative_list.html", {"items": campaigns.list_owned_creatives(request.user), "form": form}, status=status)


def _creative_page(request, creative_id, status=200, edit=None, image=None):
    """소재 상세. `edit`·`image` 는 (소재 ID, 다시 그릴 수정·이미지 폼). 보관한 소재는 읽기만(쓰는 광고·폼 없음)."""
    creative = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    owned = next((o for o in campaigns.list_owned_creatives(request.user) if o.creative.creative_id == creative.creative_id), None)
    return render(request, "console/creative_detail.html", {
        "creative": creative, "owned": owned,
        "edit": edit[1] if edit else _edit_form(creative), "image": image[1] if image else _image_form(creative),
    }, status=status)


def creative_detail(request, creative_id):
    return _creative_page(request, creative_id)


@require_POST
def creative_archive(request, creative_id):
    run_action(request, campaigns.archive_creative, request.user, creative_id,
               success="소재를 삭제했습니다. 이미 나간 광고의 기록은 남고, 목록과 광고 만들기에서는 보이지 않습니다.")
    return redirect("creative_list")


def _back(request, creative_id):
    """소재 폼이 돌아갈 곳: (돌아갈 응답, 다시 그리기). 숨김 칸 `ad_group_id` 가 있으면 그 광고 상세(남의 것·없는 것은 404), 없으면 소재 상세."""
    raw = request.POST.get("ad_group_id")
    if raw:
        group_id = fetch(campaigns.get_ad_group, request.user, raw).ad_group_id
        return redirect("ad_group_detail", ad_group_id=group_id), lambda status, **forms: _ad_page(request, group_id, status=status, **forms)
    return redirect("creative_detail", creative_id=creative_id), lambda status, **forms: _creative_page(request, creative_id, status=status, **forms)


@require_POST
def creative_edit(request, creative_id):
    """제목·이동 주소 — 이 소재를 쓰는 모든 광고에 다음 결정부터 적용된다(과거 결정은 그대로)."""
    current = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    back, redraw = _back(request, creative_id)
    form = _edit_form(current, request.POST)
    if not form.is_valid():
        return redraw(400, edit=(current.creative_id, form))
    changes = {name: form.cleaned_data[name] for name in CreativeEditForm.EDITABLE if name in form.changed_data}
    if not changes:
        messages.info(request, "바뀐 것이 없습니다.")
        return back
    try:
        campaigns.update_creative(request.user, creative_id, changes, expected_updated_at=form.cleaned_data["updated_at"])
    except HANDLED as e:
        form_errors(form, e)
        return redraw(status_of(e), edit=(current.creative_id, form))
    messages.success(request, "소재를 수정했습니다. 이 소재를 쓰는 모든 광고에 다음 결정부터 적용됩니다.")
    return back


@require_POST
def creative_image(request, creative_id):
    current = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    back, redraw = _back(request, creative_id)
    form = _image_form(current, request.POST, request.FILES)
    if not form.is_valid():
        return redraw(400, image=(current.creative_id, form))
    try:
        campaigns.replace_creative_image(request.user, creative_id, form.cleaned_data["image"], expected_updated_at=form.cleaned_data["updated_at"])
    except HANDLED as e:
        form_errors(form, e, image_field="image")
        return redraw(status_of(e), image=(current.creative_id, form))
    messages.success(request, "이미지를 바꿨습니다. 이전 이미지는 이미 나간 광고를 위해 보관합니다.")
    return back


@require_safe
def creative_image_file(request, creative_id):
    """광고주 본인 소재의 현재 이미지(계획 S4). 공개 경로(`/assets/…`)는 중단·종료 캠페인의 이미지를 막지만, 광고주는 자기 소재를 계속 봐야 한다.
    소유를 확인한 뒤에만 내려 주고(남의 것·익명은 404), 공개 경로와 같은 `nosniff` 에 캐시는 남기지 않는다(기본 `no-store`)."""
    creative = fetch(campaigns.get_creative, request.user, creative_id)
    if not asset_exists(creative.image_name):
        raise Http404
    return FileResponse(open_asset(creative.image_name), content_type=content_type(creative.image_name))
