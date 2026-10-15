"""광고주 캠페인 화면(Step 3-2b): 목록(상태·켜기/끄기·오늘 소진·최근 성과), 만들기(6-9d — 광고는 따로), 상세(수정·끝내기·중단 사유와 재검토 요청·광고그룹).
뷰는 서비스를 부르고 그리기만 한다 — 상태 규칙(끝난·중단된 캠페인)은 서비스가 판단하고, 화면은 그 오류를 보일 뿐이다(계획 3-2b 완료 조건)."""
import secrets

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from campaigns import api as campaigns

from ..errors import HANDLED, fetch, message_of, run_action, submit
from ..forms import CampaignCreateForm, CampaignEditForm, ReviewRequestForm
from ..queries.campaigns import campaign_page, campaign_rows, placement_summary
from .common import present


def _now():
    return timezone.now()


STATUS_CHIPS = (("", "전체"), *((s.value, s.label) for s in campaigns.CampaignStatus))  # 목록의 상태 칩(시안 v2): 값, 이름
SEARCH_MAX = 100


def campaign_list(request):
    """캠페인 목록. `?status=`(상태 칩)·`?q=`(이름 검색)는 GET 이라 JS 없이 된다(6-21c). 거르기는 이미 읽은 줄에서 — 질의 수는 그대로다.
    칩의 건수는 거르기 전 전체에서 센다. 모르는 상태 값은 전체로 본다."""
    rows = campaign_rows(request.user, _now())
    status = request.GET.get("status", "")
    status = status if status in dict(STATUS_CHIPS) else ""
    query = request.GET.get("q", "").strip()[:SEARCH_MAX]
    counts = {value: sum(1 for r in rows if not value or r.campaign.status == value) for value, _ in STATUS_CHIPS}
    shown = [r for r in rows if (not status or r.campaign.status == status) and query.casefold() in r.campaign.name.casefold()]
    return present(request, "console/campaign_list.html", {
        "rows": shown, "chips": [(value, label, counts[value]) for value, label in STATUS_CHIPS], "status": status, "q": query, "total": len(rows),
    })


def campaign_create(request):
    """캠페인만 만든다(이름·기간·일예산). 폼마다 새 요청 키를 실어 두 번 누름·동시 제출·응답 실패 뒤 재시도도 하나만 만든다(키가 캠페인 행에 저장된다)."""
    if request.method != "POST":
        initial = {"starts_at": _now().replace(second=0, microsecond=0), "request_key": secrets.token_urlsafe(16)}
        return present(request, "console/campaign_create.html", {"form": CampaignCreateForm(initial=initial)})
    if not request.POST.get("request_key"):
        messages.warning(request, "화면이 오래됐거나 올바르지 않은 요청입니다. 새로 불러와 다시 만드세요.")
        return redirect("campaign_create")
    try:  # 이미 성공한 제출의 다시 보냄은 폼 검증보다 먼저 처음 결과로(광고 만들기와 같다)
        done = campaigns.campaign_created_by_key(request.user, request.POST["request_key"])
    except HANDLED as e:
        messages.error(request, message_of(e))
        return redirect("campaign_create")
    if done is not None:
        messages.success(request, "이미 만든 캠페인입니다(같은 화면을 다시 보내도 하나만 만듭니다).")
        return redirect("campaign_detail", campaign_id=done.campaign_id)
    form = CampaignCreateForm(request.POST)
    c, status = submit(form, lambda d: campaigns.create_campaign(request.user, d["name"], d["starts_at"], d["ends_at"], d["daily_budget"], request_key=d["request_key"]))
    if status is not None:
        return present(request, "console/campaign_create.html", {"form": form}, status=status)
    messages.success(request, "캠페인을 만들었습니다. 이제 이 캠페인에 광고를 만드세요.")
    return redirect("campaign_detail", campaign_id=c.campaign_id)


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
        _, status = submit(form, lambda d: campaigns.update_campaign(request.user, campaign.campaign_id, changes, expected_updated_at=d["updated_at"]))
        if status is None:
            messages.success(request, "캠페인을 수정했습니다.")
            return redirect("campaign_detail", campaign_id=campaign.campaign_id)
    elif request.method == "POST":
        status = 400
    return present(request, "console/campaign_detail.html", {
        "campaign": campaign, "today": today, "reviews": reviews, "form": form, "review_form": ReviewRequestForm(),
        "groups": [(g, placement_summary(g)) for g in groups],
    }, status=status)


@require_POST
def campaign_status(request, campaign_id):
    """켜기·끄기(ACTIVE↔PAUSED). 바꿀 값이 분명한 동작이라 화면이 본 버전과 대조하지 않는다. 중단·끝난 캠페인은 서비스가 거절한다."""
    target = request.POST.get("status", "")
    run_action(request, campaigns.update_campaign, request.user, campaign_id, {"status": target},
               success="캠페인을 켰습니다." if target == "ACTIVE" else "캠페인을 껐습니다.")
    if request.POST.get("back") == "list":  # 처리 뒤 돌아갈 곳은 정한 값만(열린 리다이렉트 없음). 없으면 상세
        return redirect("campaign_list")
    return redirect("campaign_detail", campaign_id=campaign_id)


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
