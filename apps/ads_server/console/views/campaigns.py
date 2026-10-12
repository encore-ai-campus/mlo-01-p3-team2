"""광고주 캠페인 화면(Step 3-2b): 목록(상태·켜기/끄기·오늘 소진·최근 성과), 상세(수정·끝내기·중단 사유와 재검토 요청·광고그룹).
뷰는 서비스를 부르고 그리기만 한다 — 상태 규칙(끝난·중단된 캠페인)은 서비스가 판단하고, 화면은 그 오류를 보일 뿐이다(계획 3-2b 완료 조건)."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from campaigns import api as campaigns

from ..errors import HANDLED, fetch, form_errors, run_action, status_of
from ..forms import CampaignEditForm, ReviewRequestForm
from ..queries.campaigns import campaign_page, campaign_rows, placement_summary


def _now():
    return timezone.now()


def campaign_list(request):
    return render(request, "console/campaign_list.html", {"rows": campaign_rows(request.user, _now())})


def _edit_initial(campaign):
    ends_at = campaign.ends_at.replace(second=0, microsecond=0) if campaign.ends_at else None  # 화면은 분 단위 — 그대로 내면 '바뀌지 않음'으로 본다
    return {"name": campaign.name, "daily_budget": campaign.daily_budget, "ends_at": ends_at, "updated_at": campaign.updated_at.isoformat()}


def campaign_detail(request, campaign_id):
    now = _now()
    campaign, today, groups, reviews = fetch(campaign_page, request.user, campaign_id, now)
    form = CampaignEditForm(request.POST or None, initial=_edit_initial(campaign))
    status = 200
    if request.method == "POST" and form.is_valid():
        changes = {name: form.cleaned_data[name] for name in CampaignEditForm.EDITABLE if name in form.changed_data}
        if not changes:
            messages.info(request, "바뀐 것이 없습니다.")
            return redirect("campaign_detail", campaign_id=campaign.campaign_id)
        try:
            campaigns.update_campaign(request.user, campaign.campaign_id, changes, expected_updated_at=form.cleaned_data["updated_at"])
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, "캠페인을 수정했습니다.")
            return redirect("campaign_detail", campaign_id=campaign.campaign_id)
    elif request.method == "POST":
        status = 400
    return render(request, "console/campaign_detail.html", {
        "campaign": campaign, "today": today, "reviews": reviews, "form": form, "review_form": ReviewRequestForm(),
        "groups": [(g, placement_summary(g)) for g in groups],
    }, status=status)


_BACK = {"list": "campaign_list"}  # 처리 뒤 돌아갈 곳(정한 값만 — 열린 리다이렉트 없음). 없으면 상세


def _back(request, campaign_id):
    target = _BACK.get(request.POST.get("back"))
    return redirect(target) if target else redirect("campaign_detail", campaign_id=campaign_id)


@require_POST
def campaign_status(request, campaign_id):
    """켜기·끄기(ACTIVE↔PAUSED). 바꿀 값이 분명한 동작이라 화면이 본 버전과 대조하지 않는다. 중단·끝난 캠페인은 서비스가 거절한다."""
    target = request.POST.get("status", "")
    run_action(request, campaigns.update_campaign, request.user, campaign_id, {"status": target},
               success="캠페인을 켰습니다." if target == "ACTIVE" else "캠페인을 껐습니다.")
    return _back(request, campaign_id)


@require_POST
def campaign_end(request, campaign_id):
    run_action(request, campaigns.end_campaign, request.user, campaign_id, success="캠페인을 끝냈습니다. 되돌릴 수 없습니다.")
    return redirect("campaign_detail", campaign_id=campaign_id)


@require_POST
def campaign_review(request, campaign_id):
    form = ReviewRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "메모가 너무 깁니다(500자까지).")
        return redirect("campaign_detail", campaign_id=campaign_id)
    run_action(request, campaigns.create_review_request, request.user, campaign_id, form.cleaned_data["message"],
               success="재검토를 요청했습니다. 관리자가 확인하면 결과가 여기와 대시보드에 보입니다.")
    return redirect("campaign_detail", campaign_id=campaign_id)
