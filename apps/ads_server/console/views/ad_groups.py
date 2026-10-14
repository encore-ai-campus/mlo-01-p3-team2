"""광고그룹(화면의 "광고") 상세(Step 3-2d): 위치별 결과, 입찰 이력과 새 입찰(낙관적 잠금), 이름·위치·켜기/끄기, 이미지(소재).
이미지는 **고르기만** 하고(내 이미지 중 하나 — 연결은 고를 때 함께), 올리기는 따로 둔다(6-11). 이미지의 제목·주소 수정과 교체는 소재 상세(`views/creatives.py`).

동작마다 작은 폼을 따로 둔다 — 한 칸을 바꾸는 제출이 다른 칸을 옛 값으로 덮지 않는다(같은 칸은 화면이 본 변경 시각과 대조한다).
뷰는 서비스를 부르고 그리기만 한다. 입찰은 추가만 된다(서비스 규칙). 위치별 결과에는 반응 유형별 예상 과금을 함께 보인다(6-10d).
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from campaigns import api as campaigns

from ..errors import fetch, run_action, submit
from ..forms import BidForm, CreativeUploadForm, GroupNameForm, GroupSlotsForm
from ..queries.ad_groups import ad_group_page
from .ads import effect_row


def ad_group_detail(request, ad_group_id, status=200, **bound):
    """상세 화면. `bound` 는 오류와 함께 다시 그릴 폼(제출 뷰가 넘긴다)."""
    page = fetch(ad_group_page, request.user, ad_group_id)
    group = page.group
    forms = {
        "bid_form": BidForm(initial={"expected_version": group.current_bid.bid_version if group.current_bid else None}),
        "name_form": GroupNameForm(initial={"name": group.name, "updated_at": group.updated_at.isoformat()}),
        "slots_form": GroupSlotsForm(slots=page.choices, initial={"slot_ids": [str(s) for s in group.slot_ids], "updated_at": group.updated_at.isoformat()}),
        "upload_form": CreativeUploadForm(prefix="new"),
        **bound,
    }
    return render(request, "console/ad_group_detail.html", {
        "page": page, "group": group, "effects": [effect_row(page.linked.get(e.slot_id), e) for e in page.effects], **forms,
    }, status=status)


def _submit(request, ad_group_id, form, call, done, image_field=None, **redraw):
    """폼 하나의 제출(`console.errors.submit`): 완료면 메시지와 함께 상세로 돌아가고, 아니면 상세를 그 폼과 함께 다시 그린다(`redraw` = 다시 그릴 폼)."""
    _, status = submit(form, call, image_field=image_field)
    if status is not None:
        return ad_group_detail(request, ad_group_id, status=status, **redraw)
    messages.success(request, done)
    return redirect("ad_group_detail", ad_group_id=ad_group_id)


@require_POST
def ad_group_bid(request, ad_group_id):
    form = BidForm(request.POST)
    return _submit(request, ad_group_id, form, lambda d: campaigns.add_bid(request.user, ad_group_id, d["amount"], d["expected_version"]),
                   "새 입찰을 넣었습니다. 구성별 결과가 바뀌었을 수 있습니다.", bid_form=form)


@require_POST
def ad_group_name(request, ad_group_id):
    form = GroupNameForm(request.POST)
    return _submit(request, ad_group_id, form, lambda d: campaigns.update_ad_group(request.user, ad_group_id, {"name": d["name"]}, expected_updated_at=d["updated_at"]),
                   "이름을 바꿨습니다.", name_form=form)


@require_POST
def ad_group_slots(request, ad_group_id):
    page = fetch(ad_group_page, request.user, ad_group_id)
    form = GroupSlotsForm(request.POST, slots=page.choices)
    return _submit(request, ad_group_id, form, lambda d: campaigns.update_ad_group(request.user, ad_group_id, {"slot_ids": d["slot_ids"]}, expected_updated_at=d["updated_at"]),
                   "구성을 바꿨습니다.", slots_form=form)


@require_POST
def ad_group_creative_upload(request, ad_group_id):
    """"이미지 업로드"(6-11): 내 이미지(소재)를 올리기만 한다 — 이 광고에 연결·선택하지 않는다. 올린 것은 위 "이미지"에서 고른다. 남의 광고 화면이면 404."""
    fetch(campaigns.get_ad_group, request.user, ad_group_id)
    form = CreativeUploadForm(request.POST, request.FILES, prefix="new")
    return _submit(request, ad_group_id, form, lambda d: campaigns.create_creative(request.user, None, d["title"], d["redirect_url"], d["image"]),
                   "이미지를 올렸습니다. 위 ‘이미지’에서 고르면 이 광고에 나갑니다.", image_field="image", upload_form=form)


@require_POST
def ad_group_creative_select(request, ad_group_id):
    """"이미지"(6-11): 내 이미지 중 하나를 이 광고에 나갈 것으로 고른다 — 아직 연결되지 않았으면 같은 트랜잭션에서 연결한다(다음 결정부터, 이미 나간 결정은 그대로).
    남의 이미지·보관한 이미지는 서비스가 404."""
    run_action(request, campaigns.link_creative, request.user, ad_group_id, request.POST.get("creative_id"), select=True,
               success="이 광고에 나갈 이미지를 바꿨습니다. 다음 결정부터 적용됩니다.")
    return redirect("ad_group_detail", ad_group_id=ad_group_id)


@require_POST
def ad_group_enabled(request, ad_group_id):
    enabled = request.POST.get("enabled") == "1"
    run_action(request, campaigns.update_ad_group, request.user, ad_group_id, {"enabled": enabled}, success="광고를 켰습니다." if enabled else "광고를 껐습니다.")
    return redirect("ad_group_detail", ad_group_id=ad_group_id)
