"""퍼널 집계(설계 §10 "퍼널 집계", C6 `/reports/daily`). **조회 시점에 인정된 반응을 결정과 묶어 세는 읽기 전용 함수**다 — 별도 테이블·쓰기가 없다.

반응이 많아져 느려지면 이 함수 안쪽만 일별 카운터나 파이프라인 결과(C4)로 바꾼다. 호출하는 쪽(콘솔)은 그대로다.

- 범위는 광고주의 것으로 좁힌다: 결정에 기록된 `owner_id`·`campaign_id`·`ad_group_id`(과금과 같은 근거). 남의 캠페인·광고그룹은 없는 것과 같다(404).
- 날짜는 **수신 시각(`received_at`)** 의 예산 일(기본 UTC 자정) 기준이고, 구간은 `from` 포함 `to` 미포함, 일 경계에 맞아야 하며 최대 92일이다.
- 노출·클릭·전환은 `ACCEPTED` 만 센다(일괄 슬롯은 사람마다 한 건씩 센다). `spent` 는 **실제로 받은 포인트**다(잔액이 모자라 덜 받았으면 그만큼).
  소진은 원장의 과금이다 — 캠페인·광고주 범위는 캠페인의 과금 줄을 예산 일로 묶고, 원장에 광고그룹이 없는 광고그룹 범위는 그 광고그룹 결정의 반응으로 과금을 찾는다.
- 전환율은 **클릭 코호트 기준**이다: 그 구간에 받은 클릭 중 인정된 전환이 이어진 클릭 수(`converted_clicks`) / 클릭 수. 전환 수는 수신일 기준이라 이전 구간 클릭의 전환이 섞인다.
- 질의 수는 데이터 양과 무관하다(광고그룹 범위의 원장 조회는 반응 500건당 한 번).
"""
from collections import defaultdict
from datetime import timedelta

from django.http import Http404
from django.db.models import Count, Exists, OuterRef, Q, Subquery

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import errors, require_advertiser

from .models import Decision, Reaction, ReactionStatus, ReactionType
from .processing import reaction_ref
from .types import DailyReportView, ReportRow, ReportTotals

MAX_DAYS = 92


def _check_window(start, end):
    problems = []
    for pointer, value in (("/from", start), ("/to", end)):
        if getattr(value, "tzinfo", None) is None:
            problems.append({"pointer": pointer, "message": "UTC 시각이어야 합니다."})
        elif billing.day_start(billing.budget_day_of(value)) != value:
            problems.append({"pointer": pointer, "message": "예산 일 경계(기본 UTC 자정)에 맞아야 합니다."})
    if problems:
        raise errors.InvalidRequest(errors=problems)
    if end <= start:
        raise errors.InvalidRequest(errors=[{"pointer": "/to", "message": "to 는 from 보다 뒤여야 합니다."}])
    if (billing.budget_day_of(end) - billing.budget_day_of(start)).days > MAX_DAYS:
        raise errors.InvalidRequest(errors=[{"pointer": "/to", "message": f"구간은 최대 {MAX_DAYS}일입니다."}])


def _scope(user, campaign_id, ad_group_id):
    """(결정 필터, 광고그룹 보기 또는 None). 남의 캠페인·광고그룹, 서로 맞지 않는 쌍은 `Http404`(다른 광고주 객체 조회와 같은 규약)."""
    filters = {"owner_id": user.pk}
    group = None
    if campaign_id is not None:
        filters["campaign_id"] = campaigns.get_campaign(user, campaign_id).campaign_id  # 소유 확인(남의 것은 404)
    if ad_group_id is not None:
        group = campaigns.get_ad_group(user, ad_group_id)
        if campaign_id is not None and group.campaign_id != filters["campaign_id"]:
            raise Http404
        filters["ad_group_id"] = group.ad_group_id
    return filters, group


def _counts(decision_filters, since, until, key=None):
    """`{날짜: {지표: 수}}` — **SQL 한 번**(질의 한 번 = 같은 읽기 상태). `key` 로 묶는 기준을 바꾼다(기본: 수신일, 캠페인별 합계는 결정의 캠페인).

    노출·클릭·전환 수와 `converted_clicks`(클릭 코호트: 같은 (결정, 사람)에 인정된 전환이 있는 클릭 수, 전환이 구간 뒤에 와도 센다. 날짜는 **클릭**의 수신일)를
    한 SELECT 에서 센다. 분자와 분모를 따로 읽으면(`READ COMMITTED` 는 SELECT 마다 새 스냅샷) 그 사이에 인정된 퍼널이 한쪽에만 들어가 전환율이 1 을 넘는다.
    전환은 같은 사람의 서버 클릭 뒤에만 인정되고 유형당 인정은 한 건이라, 클릭 하나에 전환이 둘 이상 매달리지 않는다(`converted_clicks` <= `clicks`).
    """
    decisions = Decision.objects.filter(**decision_filters).values("decision_id")
    converted = Reaction.objects.filter(status=ReactionStatus.ACCEPTED, type=ReactionType.CONVERSION, decision_id=OuterRef("decision_id"), person_id=OuterRef("person_id"))
    by_type = lambda rtype: Count("inbox_id", filter=Q(type=rtype))  # noqa: E731
    rows = (
        Reaction.objects.filter(status=ReactionStatus.ACCEPTED, received_at__gte=since, received_at__lt=until, decision_id__in=decisions)
        .annotate(key=key if key is not None else billing.budget_day_expression("received_at")).values("key").annotate(
            impressions=by_type(ReactionType.IMPRESSION), clicks=by_type(ReactionType.CLICK), conversions=by_type(ReactionType.CONVERSION),
            converted_clicks=Count("inbox_id", filter=Q(type=ReactionType.CLICK) & Q(Exists(converted))),
        ).values_list("key", "impressions", "clicks", "conversions", "converted_clicks")
    )
    return {k: dict(impressions=i, clicks=c, conversions=v, converted_clicks=cc) for k, i, c, v, cc in rows}


def _spent_by_day(user, group, decision_filters, since, until, first_day, last_day):
    """`{날짜: 받은 포인트}`."""
    if group is None:
        ids = [decision_filters["campaign_id"]] if "campaign_id" in decision_filters else campaigns.campaign_ids_of(user)
        return billing.spend_by_day(ids, first_day, last_day)
    # 광고그룹: 원장의 과금 줄에는 캠페인만 있으므로, 이 광고그룹 결정의 인정된 반응(모든 유형 — 6-10c)에 대한 원장 과금을 읽는다
    decisions = Decision.objects.filter(**decision_filters).values("decision_id")
    reactions = (
        Reaction.objects.filter(status=ReactionStatus.ACCEPTED, received_at__gte=since, received_at__lt=until, decision_id__in=decisions)
        .annotate(day=billing.budget_day_expression("received_at")).values_list("media_id", "reaction_id", "day")
    )
    days = {reaction_ref(media_id, reaction_id): day for media_id, reaction_id, day in reactions}
    spent = defaultdict(int)
    for ref, amount in billing.charged_amounts(days).items():
        spent[days[ref]] += amount
    return dict(spent)


def daily_report(owner, start, end, campaign_id=None, ad_group_id=None):
    """광고주의 일별 성과. `start` 포함 `end` 미포함(둘 다 예산 일 경계의 UTC 시각, 최대 92일).

    `campaign_id`·`ad_group_id` 로 범위를 좁힐 수 있다. 직전의 같은 길이 구간은 `previous_totals` 로 함께 돌려준다.
    """
    require_advertiser(owner, "광고주만 볼 수 있습니다.")
    _check_window(start, end)
    first, last = billing.budget_day_of(start), billing.budget_day_of(end)
    length = last - first
    previous_start = billing.day_start(first - length)
    filters, group = _scope(owner, campaign_id, ad_group_id)
    counts = _counts(filters, previous_start, end)  # 직전 구간과 이번 구간을 한 번에 가져와 나눈다(SQL 한 번)
    spent = _spent_by_day(owner, group, filters, previous_start, end, first - length, last)

    def totals_of(days):
        sums = dict.fromkeys(("impressions", "clicks", "conversions", "converted_clicks"), 0)
        for day in days:
            for field, n in counts.get(day, {}).items():
                sums[field] += n
        return ReportTotals(spent=sum(spent.get(day, 0) for day in days), **sums)

    days = [first + timedelta(days=i) for i in range(length.days)]
    previous_days = [first - length + timedelta(days=i) for i in range(length.days)]
    return DailyReportView(
        start=start, end=end, rows=tuple(ReportRow(date=day, totals=totals_of([day])) for day in days),
        totals=totals_of(days), previous_totals=totals_of(previous_days),
    )


def campaign_totals(owner, start, end):
    """기간의 캠페인별 합계 `{campaign_id: ReportTotals}`(대시보드의 상위 캠페인 표, Step 3-2a). `daily_report` 와 같은 규칙이다 — 인정된 반응을
    수신일로 세고, `spent` 는 실제로 받은 포인트. 반응·소진이 없는 캠페인은 결과에 없다. 질의 수는 데이터 양과 무관(반응 1 + 소진 1 + 캠페인 목록 1)."""
    require_advertiser(owner, "광고주만 볼 수 있습니다.")
    _check_window(start, end)
    campaign_of = Subquery(Decision.objects.filter(pk=OuterRef("decision_id")).values("campaign_id")[:1])
    counts = _counts({"owner_id": owner.pk}, start, end, key=campaign_of)
    spent = billing.spend_by_campaign(campaigns.campaign_ids_of(owner), billing.budget_day_of(start), billing.budget_day_of(end))
    zero = dict.fromkeys(("impressions", "clicks", "conversions", "converted_clicks"), 0)
    return {cid: ReportTotals(spent=spent.get(cid, 0), **{**zero, **counts.get(cid, {})}) for cid in set(counts) | set(spent)}
