"""접수와 판정의 순서 규약(설계 §10 "판정 설계 기준" ② 결정성).

판정은 "먼저 접수된 반응"(`received_at`, 동률이면 `inbox_id`)을 기준으로 한다: 같은 유형의 인정 대표, 앞 단계 반응의 도착 시각, 표시 교체 신호.
그런데 접수는 INSERT 와 커밋 사이에 시간이 걸리고, 그 사이의 반응은 다른 연결에서 **보이지 않는다**. 더 이른 `received_at` 을 가진 반응이 아직 커밋 전이면,
판정이 그것을 모른 채 뒤의 반응을 대표로 굳혀 버린다(최종 데이터에는 더 이른 유효 반응이 있는데도).

그래서 접수와 판정이 **결정 행의 잠금**을 공유한다.
- 접수(`lock_for_receipt`): 트랜잭션 안에서 결정 행을 `FOR UPDATE` 로 잠근 **뒤에** 수신 시각을 정하고 INSERT 한다(**결정 소유 매체의 접수만** — 남의 보고는 잠그지도 기다리지도 않는다). 잠금은 커밋까지 간다.
  같은 결정의 접수는 이 잠금으로 줄을 서므로 커밋 순서 = 시각 순서다.
- 판정(`wait_for_inflight_receipts`): 판정을 시작하기 전에 같은 잠금을 한 번 지나간다. 진행 중인 접수가 있으면 그 커밋까지 기다리고, 지나간 뒤에 시작하는 접수는
  (시각이 잠근 뒤에 정해지므로) 이 반응보다 늦은 `received_at` 을 갖는다. 클릭은 표시 교체 신호가 **이후 결정**의 노출이므로 그 결정들(클릭 접수 시각까지, 클릭 기간 안)도 지나간다.

잠금은 결정 단위라 서로 다른 결정의 접수·판정은 막지 않는다. 판정은 잠금을 쥔 채 진행하지 않고(과금 트랜잭션을 길게 막지 않는다) 지나가기만 한다.
잠금 순서는 결정 ID 순으로 고정해 판정끼리 교착하지 않고, 접수는 잠금을 하나만 잡는다.

**매체 생명주기도 같은 방식이다**(설계 §10 "매체 비활성화와 판정·결정의 순서", 6-2). 비활성화는 매체 행을 배타 잠금으로 쥔 **뒤에** 비활성화 시각을 정하고 커밋한다.
판정은 결정 행들 **다음에** 결정 소유 매체 행을 공유 잠금으로 지나간다(`masters.media_active_for_share`) — 진행 중인 비활성화가 있으면 그 커밋까지 기다리므로,
그 비활성화가 이 반응의 접수 뒤인지 앞인지가 판정 순서와 무관하게 정해진다. 지나간 뒤에 시작하는 비활성화는 이 반응보다 늦은 시각을 갖는다.
잠금 순서는 결정 행 → 매체 행이고, 비활성화는 매체 행만 잡으므로 순환이 없다.
전제: 서버 시계는 한 방향으로 흐른다(NTP 보정으로 시계가 크게 뒤로 가는 경우는 다루지 않는다).
"""
from django.conf import settings
from django.db import transaction

from masters import api as masters

from .facts import later_decisions
from .models import Decision, Reaction, ReactionStatus, ReactionType


def _owner(decision_id):
    """결정을 만든 매체(없으면 `None`) — **잠금 없는 일반 조회**."""
    return Decision.objects.filter(pk=decision_id).values_list("media_id", flat=True).first()


def lock_for_receipt(decision_id, reporting_media_id):
    """접수 트랜잭션의 **첫 일**: 결정 행을 잠근다(커밋까지). 이 호출 **뒤에** 수신 시각을 정해야 한다.

    **결정 소유 매체의 접수만** 잠근다. 접수는 없는 결정·남의 결정에 대한 보고도 저장하지만(존재를 알리지 않으려고) 그런 보고는 어차피 거부되고 판정에 쓰이지도 않는다
    (`scoped_reactions`) — 그런 보고가 소유 매체의 접수·판정을 기다리게 하거나 막으면 안 된다. 소유 확인은 잠금 **전**의 일반 조회로 한다:
    `FOR UPDATE` 질의에 `media_id` 조건만 더하면 InnoDB 는 조건에 걸리기 전에 행을 잠그므로 남의 보고도 같은 잠금을 기다린다.
    """
    if _owner(decision_id) != reporting_media_id:
        return
    list(Decision.objects.select_for_update().filter(pk=decision_id).values_list("pk", flat=True))


def wait_for_inflight_receipts(inbox_id):
    """반응을 판정하기 전에, 이 반응의 판정에 영향을 줄 수 있는 **진행 중인 접수와 매체 비활성화**가 커밋될 때까지 기다린다. 잠금은 바로 놓는다."""
    row = Reaction.objects.filter(pk=inbox_id, status=ReactionStatus.RECEIVED).values("media_id", "decision_id", "type", "received_at").first()
    if row is None:
        return
    with transaction.atomic():
        decision = Decision.objects.filter(pk=row["decision_id"]).first()
        if decision is None or decision.media_id != row["media_id"]:
            return  # 없는 결정·남의 결정에 대한 보고는 어차피 거부된다 — 소유 매체의 접수를 기다릴 이유가 없다
        ids = [decision.decision_id]
        click_window = settings.REACTION_CLICK_WINDOW_SECONDS
        if row["type"] == ReactionType.CLICK and (row["received_at"] - decision.decided_at).total_seconds() <= click_window:  # 기간 밖 클릭은 어차피 거부된다
            ids += list(later_decisions(decision).filter(decided_at__lte=row["received_at"]).values_list("decision_id", flat=True))
        list(Decision.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
        masters.media_active_for_share(decision.media_id)  # 결정 행 다음: 진행 중인 비활성화(결정 소유 매체)의 커밋을 기다린다
