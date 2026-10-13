"""소재 화면(6-9d, 설계 §10 "소재 목록"): 내 소재 목록(올리기·쓰는 광고·삭제), 소재 상세(제목/주소 수정·이미지 교체·삭제), 소재 이미지.

소재는 광고주 소유이고 여러 광고에 연결된다. 수정·이미지 교체는 소재 상세에서만 한다 — 광고 상세는 내 이미지 중 하나를 고르기만 한다(6-11).
"삭제"는 보관이다 — 끝나지 않은 캠페인의 광고에 연결돼 있으면 서비스가 거절한다(409).
"""
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from assets.api import asset_exists, content_type, open_asset
from campaigns import api as campaigns

from ..errors import fetch, run_action, submit
from ..forms import CreativeEditForm, CreativeUploadForm, ImageForm


def creative_list(request):
    """내 소재(보관하지 않은 것)와 소재마다 쓰는 광고. 여기서 올린 소재는 아직 어느 광고에도 연결되지 않는다."""
    form = CreativeUploadForm(request.POST or None, request.FILES or None, prefix="new")
    status = 200
    if request.method == "POST":
        c, status = submit(form, lambda d: campaigns.create_creative(request.user, None, d["title"], d["redirect_url"], d["image"]), image_field="image")
        if status is None:
            messages.success(request, "소재를 올렸습니다. 광고 만들기나 광고 상세에서 이 소재를 쓸 수 있습니다.")
            return redirect("creative_detail", creative_id=c.creative_id)
    return render(request, "console/creative_list.html", {"items": campaigns.list_owned_creatives(request.user), "form": form}, status=status)


def _edit_form(creative, data=None):
    initial = {"title": creative.title, "redirect_url": creative.redirect_url, "updated_at": creative.updated_at.isoformat()}
    return CreativeEditForm(data, prefix=str(creative.creative_id), initial=initial)


def _image_form(creative, data=None, files=None):
    return ImageForm(data, files, prefix=str(creative.creative_id), auto_id="image_%s", initial={"updated_at": creative.updated_at.isoformat()})  # id 는 수정 폼과 다르게


def creative_detail(request, creative_id, status=200, edit=None, image=None):
    """소재 상세. `edit`·`image` 는 다시 그릴 수정·이미지 폼(제출 뷰가 넘긴다). 보관한 소재는 읽기만(쓰는 광고·폼 없음)."""
    creative = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    owned = next((o for o in campaigns.list_owned_creatives(request.user) if o.creative.creative_id == creative.creative_id), None)
    return render(request, "console/creative_detail.html", {
        "creative": creative, "owned": owned,
        "edit": edit or _edit_form(creative), "image": image or _image_form(creative),
    }, status=status)


@require_POST
def creative_archive(request, creative_id):
    run_action(request, campaigns.archive_creative, request.user, creative_id,
               success="소재를 삭제했습니다. 이미 나간 광고의 기록은 남고, 목록과 광고 만들기에서는 보이지 않습니다.")
    return redirect("creative_list")


@require_POST
def creative_edit(request, creative_id):
    """제목·이동 주소 — 이 소재를 쓰는 모든 광고에 다음 결정부터 적용된다(과거 결정은 그대로)."""
    current = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    form = _edit_form(current, request.POST)
    if not form.is_valid():
        return creative_detail(request, creative_id, status=400, edit=form)
    changes = {name: form.cleaned_data[name] for name in CreativeEditForm.EDITABLE if name in form.changed_data}
    if not changes:
        messages.info(request, "바뀐 것이 없습니다.")
        return redirect("creative_detail", creative_id=current.creative_id)
    _, status = submit(form, lambda d: campaigns.update_creative(request.user, creative_id, changes, expected_updated_at=d["updated_at"]))
    if status is not None:
        return creative_detail(request, creative_id, status=status, edit=form)
    messages.success(request, "소재를 수정했습니다. 이 소재를 쓰는 모든 광고에 다음 결정부터 적용됩니다.")
    return redirect("creative_detail", creative_id=current.creative_id)


@require_POST
def creative_image(request, creative_id):
    current = fetch(campaigns.get_creative, request.user, creative_id)  # 남의 소재는 404
    form = _image_form(current, request.POST, request.FILES)
    _, status = submit(form, lambda d: campaigns.replace_creative_image(request.user, creative_id, d["image"], expected_updated_at=d["updated_at"]),
                       image_field="image")
    if status is not None:
        return creative_detail(request, creative_id, status=status, image=form)
    messages.success(request, "이미지를 바꿨습니다. 이전 이미지는 이미 나간 광고를 위해 보관합니다.")
    return redirect("creative_detail", creative_id=current.creative_id)


@require_safe
def creative_image_file(request, creative_id):
    """광고주 본인 소재의 현재 이미지(계획 S4). 공개 경로(`/assets/…`)는 중단·종료 캠페인의 이미지를 막지만, 광고주는 자기 소재를 계속 봐야 한다.
    소유를 확인한 뒤에만 내려 주고(남의 것·익명은 404), 공개 경로와 같은 `nosniff` 에 캐시는 남기지 않는다(기본 `no-store`)."""
    creative = fetch(campaigns.get_creative, request.user, creative_id)
    if not asset_exists(creative.image_name):
        raise Http404
    return FileResponse(open_asset(creative.image_name), content_type=content_type(creative.image_name))
