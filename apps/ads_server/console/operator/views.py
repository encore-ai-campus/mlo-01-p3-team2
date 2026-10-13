"""관리자 운영 화면(Step 3-1: 매체·슬롯·키, 입찰 정책, 광고 모니터링·중단·재검토, 광고주·포인트). 뷰는 서비스를 부르고 그리기만 한다 — 규칙은 각 서비스(masters·campaigns·billing·foundation), 예외의 화면 변환은 console/errors.

화면은 Django admin 의 모양(`admin/base_site.html`)을 쓴다. 상태를 바꾸는 주소는 POST 만 받고 처리 뒤 목록으로 돌아간다(PRG).
예외: 키 발급·교체는 **평문 키를 그 응답에 한 번만** 보여 줘야 해서 리다이렉트하지 않는다 — 대신 폼마다 새 요청 키를 실어 서비스가 한 번만 발급한다.
두 번 하면 안 되는 동작(키 발급·교체, 포인트 조정)의 요청 키는 세션이 아니라 **결과 행과 같은 트랜잭션**에 저장한다 — 세션은 요청마다 따로 읽은
사본이라 동시 제출을 막지 못하고, 처리 뒤 응답이 실패하면 다시 보낼 수 있었다(외부 검토 3-1d).
"""
import secrets

from django.contrib import admin, messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from assets.api import asset_exists, content_type, open_asset
from billing import api as billing
from campaigns import api as campaigns
from foundation.api import get_advertiser, list_advertisers, profiles, set_advertiser_active
from masters import api as masters

from ..errors import HANDLED, fetch, form_errors, message_of, run_action, status_of
from ..paging import page_of
from .forms import AdjustForm, BulkPolicyForm, KeyIssueForm, KeyRotateForm, MediaForm, PolicyForm, ReleaseForm, SlotForm


def _render(request, template, title, status=200, **context):
    return render(request, template, {**admin.site.each_context(request), "title": title, **context}, status=status)


def media_list(request):
    form = MediaForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            media = masters.create_media(request.user, form.cleaned_data["name"])
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, f"매체 ‘{media.name}’을(를) 등록했습니다.")
            return redirect("operator:media_list")
    return _render(request, "operator/media_list.html", "매체", status=400 if status == 200 and form.errors else status,
                   media=masters.list_media(request.user), form=form)


def _detail(request, media_id, status=200, slot_form=None):
    media = fetch(masters.get_media, request.user, media_id)
    return _render(
        request, "operator/media_detail.html", f"매체: {media.name}", status=status, media=media,
        slots=masters.list_slots(active_only=False, media_id=media.media_id), keys=masters.list_media_keys(request.user, media.media_id),
        slot_form=slot_form or SlotForm(), issue_form=KeyIssueForm(initial={"request_key": secrets.token_urlsafe(16)}),
        rotate_form=KeyRotateForm(initial={"request_key": secrets.token_urlsafe(16)}, auto_id="rotate_%s"),  # 한 화면의 두 폼 — 칸 id 가 겹치지 않게
    )


def media_detail(request, media_id):
    return _detail(request, media_id)


@require_POST
def media_active(request, media_id):
    run_action(request, masters.set_media_active, request.user, media_id, request.POST.get("active") == "1")
    return redirect("operator:media_list")


@require_POST
def slot_create(request, media_id):
    form = SlotForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            masters.create_slot(request.user, media_id, **form.cleaned_data)
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, f"게재 위치 ‘{form.cleaned_data['name'].strip()}’을(를) 만들었습니다.")
            return redirect("operator:media_detail", media_id=media_id)
    return _detail(request, media_id, status=status, slot_form=form)


@require_POST
def slot_active(request, slot_id):
    slot = fetch(masters.get_slot, slot_id)
    run_action(request, masters.set_slot_active, request.user, slot.slot_id, request.POST.get("active") == "1")
    return redirect("operator:media_detail", media_id=slot.media_id)


def slot_policy(request, slot_id):
    """슬롯 하나의 입찰 정책 새 버전(Step 3-1b). 폼은 현재값으로 시작하고, 본 버전을 숨김 칸으로 실어 그 사이 바뀌었으면 거절된다."""
    slot = fetch(masters.get_slot, slot_id)
    current = slot.policy
    form = PolicyForm(request.POST or None, initial={
        "floor": current.floor, "base": current.base, "cap": current.cap, "impression_share": current.impression_share, "click_share": current.click_share,
        "conversion_share": current.conversion_share, "expected_version": current.policy_version,
    })
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            masters.add_policy_version(request.user, slot.slot_id, **form.cleaned_data)
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, f"‘{slot.name}’의 입찰 정책을 새 버전으로 바꿨습니다.")
            return redirect("operator:slot_policy", slot_id=slot.slot_id)
    history = masters.list_policy_versions(request.user, slot.slot_id)
    return _render(request, "operator/slot_policy.html", f"입찰 정책: {slot.name}", status=400 if status == 200 and form.errors else status,
                   slot=slot, form=form, history=history, people=profiles([p.changed_by for p in history]), stale=status == 409)


def policy_bulk(request):
    """여러 슬롯에 같은 값으로 새 버전(Step 3-1b). 하나라도 어긋나면 전부 취소된다(서비스가 한 트랜잭션)."""
    form = BulkPolicyForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            changed = masters.add_policy_version_bulk(request.user, data.pop("slots"), **data)
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, f"게재 위치 {len(changed)}개의 입찰 정책을 새 버전으로 바꿨습니다.")
            return redirect("operator:policy_bulk")
    return _render(request, "operator/policy_bulk.html", "입찰 정책 일괄 변경", status=400 if status == 200 and form.errors else status,
                   slots=masters.list_slots(active_only=False), form=form, stale=status == 409)


def _issue_key(request, media_id, form_class, issue):
    media = fetch(masters.get_media, request.user, media_id)
    if not request.POST.get("request_key"):
        messages.warning(request, "화면이 오래됐거나 올바르지 않은 요청입니다. 새로 불러와 다시 발급하세요.")
        return redirect("operator:media_detail", media_id=media.media_id)
    form = form_class(request.POST)
    if form.is_valid():
        try:
            issued = issue(media, form.cleaned_data)
        except HANDLED as e:
            messages.error(request, message_of(e))
        else:
            response = _render(request, "operator/key_issued.html", "발급한 매체 키", media=media, issued=issued)
            response["Cache-Control"] = "no-store"  # 평문 키가 든 유일한 응답: 어디에도 남기지 않는다
            return response
    else:
        messages.error(request, "입력이 올바르지 않습니다.")
    return redirect("operator:media_detail", media_id=media.media_id)


@require_POST
def key_issue(request, media_id):
    return _issue_key(request, media_id, KeyIssueForm,
                      lambda media, data: masters.issue_media_key(request.user, media.media_id, data["label"], request_key=data["request_key"]))


@require_POST
def key_rotate(request, media_id):
    return _issue_key(request, media_id, KeyRotateForm,
                      lambda media, data: masters.rotate_media_key(request.user, media.media_id, data["grace_seconds"], data["label"],
                                                                   request_key=data["request_key"]))


@require_POST
def key_revoke(request, key_id):
    media = fetch(masters.get_media, request.user, request.POST.get("media_id"))
    run_action(request, masters.revoke_media_key, request.user, key_id, success="키를 폐기했습니다.")
    return redirect("operator:media_detail", media_id=media.media_id)


# ---------------------------------------------------------------- 광고 모니터링·중단·재검토 (Step 3-1c)

BACK = {"campaigns": "operator:campaign_monitor", "reviews": "operator:review_queue"}  # 처리 뒤 돌아갈 곳(정한 값만 — 열린 리다이렉트 없음)


def _back(request):
    return redirect(BACK.get(request.POST.get("back"), "operator:campaign_monitor"))


def campaign_monitor(request):
    """모든 광고주의 캠페인·소재(마지막 변경순). 썸네일·이동 주소 도메인·광고주를 함께 본다(S5)."""
    page = page_of(campaigns.monitoring_list(request.user), request)
    return _render(request, "operator/campaign_monitor.html", "광고 모니터링", page=page,
                   people=profiles([item.campaign.owner_id for item in page]))


@require_POST
def campaign_suspend(request, campaign_id):
    run_action(request, campaigns.suspend_campaign, request.user, campaign_id, request.POST.get("reason", ""),
               success="캠페인을 중단했습니다. 광고주 화면에 사유가 보입니다.")
    return _back(request)


@require_POST
def campaign_release(request, campaign_id):
    """화면이 본 중단 회차·재검토 요청과 지금이 다르면 해제하지 않는다(오래된 화면의 버튼이 새 중단을 풀지 않게)."""
    form = ReleaseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "화면이 오래됐거나 올바르지 않은 요청입니다. 새로 불러와 다시 시도하세요.")
        return _back(request)
    run_action(request, campaigns.release_campaign, request.user, campaign_id, expected_suspended_at=form.cleaned_data["suspended_at"],
               review_request_id=form.cleaned_data["review_request_id"] or None, success="중단을 해제했습니다. 열린 재검토 요청은 해제로 닫혔습니다.")
    return _back(request)


def review_queue(request):
    """열린 재검토 요청(오래된 것부터). 소재 썸네일을 함께 보여 판단을 돕는다."""
    items = campaigns.open_review_queue(request.user)
    return _render(request, "operator/review_queue.html", "재검토 대기", items=items, people=profiles([item.campaign.owner_id for item in items]))


@require_POST
def review_reject(request, review_request_id):
    run_action(request, campaigns.reject_review_request, request.user, review_request_id, request.POST.get("note", ""),
               success="재검토 요청을 반려했습니다. 중단은 그대로입니다.")
    return redirect("operator:review_queue")


# ---------------------------------------------------------------- 광고주·포인트 (Step 3-1d)

def advertiser_list(request):
    """광고주(최근 가입순)와 사용량 대 상한·잔액. 남용 계정을 찾아 비활성화한다(위협 모델 T2)."""
    page = page_of(list_advertisers(request.user), request)
    ids = [a.user_id for a in page]
    return _render(request, "operator/advertiser_list.html", "광고주", page=page,
                   usage=campaigns.advertiser_usage(request.user, ids), balances=billing.balances(ids))


def _advertiser_page(request, user_id, status=200, adjust_form=None):
    account = fetch(get_advertiser, request.user, user_id)
    entries, next_cursor = billing.ledger_of(request.user, account.user_id, before=request.GET.get("before"))
    return _render(request, "operator/advertiser_detail.html", f"광고주: {account.username}", status=status, account=account,
                   wallet=billing.wallet_of(request.user, account.user_id), entries=entries, next_cursor=next_cursor,
                   names=campaigns.campaign_names({e.campaign_id for e in entries if e.campaign_id}),
                   adjust_form=adjust_form or AdjustForm(initial={"request_key": secrets.token_urlsafe(16)}))


def advertiser_detail(request, user_id):
    return _advertiser_page(request, user_id)


@require_POST
def advertiser_active(request, user_id):
    active = request.POST.get("active") == "1"
    run_action(request, set_advertiser_active, request.user, user_id, active, request.POST.get("reason", ""),
               success="계정을 다시 활성화했습니다. 광고가 다시 나갑니다." if active else "계정을 비활성화했습니다. 로그인할 수 없고 광고도 나가지 않습니다.")
    return redirect("operator:advertiser_detail", user_id=user_id)


@require_POST
def advertiser_adjust(request, user_id):
    """포인트 조정(사유 필수, 0 밑으로 불가 — 서비스 `billing.adjust`). 폼마다 새 `request_key` 를 실어, 같은 폼을 다시 보내거나(두 번 누름·동시 제출)
    처리 뒤 응답이 실패해 재시도해도 **한 번만** 반영한다 — 키가 원장 줄과 같은 트랜잭션에 저장된다(세션에 기대지 않는다).
    입력 오류로 다시 그린 폼은 같은 키를 그대로 싣는다(그 키로는 아직 아무것도 반영되지 않았다)."""
    account = fetch(get_advertiser, request.user, user_id)
    if not request.POST.get("request_key"):
        messages.warning(request, "화면이 오래됐거나 올바르지 않은 요청입니다. 새로 불러와 다시 조정하세요.")
        return redirect("operator:advertiser_detail", user_id=account.user_id)
    form = AdjustForm(request.POST)
    status = 400
    if form.is_valid():
        data = form.cleaned_data
        try:
            entry = billing.adjust(request.user, account.user_id, data["amount"], data["note"], request_key=data["request_key"])
        except HANDLED as e:
            form_errors(form, e)
            status = status_of(e)
        else:
            messages.success(request, f"{entry.amount:+,} 포인트 조정이 원장에 반영됐습니다(같은 화면을 다시 보내도 한 번만 반영됩니다).")
            return redirect("operator:advertiser_detail", user_id=account.user_id)
    return _advertiser_page(request, account.user_id, status=status, adjust_form=form)


@require_safe
def asset(request, name):
    """관리자 전용 소재 이미지. 공개 경로(`/assets/…`)는 중단·종료 캠페인의 이미지를 막지만, 관리자는 그 소재를 봐야 판단할 수 있다.
    관리자 경로 아래라 다른 사람에게는 404 다. 형식이 틀린 이름은 저장소가 거른다(`asset_exists` 거짓 → 404). 캐시는 기본(`no-store`)."""
    if not asset_exists(name):
        raise Http404
    return FileResponse(open_asset(name), content_type=content_type(name))
