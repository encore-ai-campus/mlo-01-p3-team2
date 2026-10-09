"""접수와 판정의 순서 규약(설계 §10 "판정 설계 기준" ② 결정성).

판정은 "먼저 접수된 반응"(`received_at`, 동률이면 `inbox_id`)을 기준으로 한다: 같은 유형의 인정 대표, 앞 단계 반응의 도착 시각, 표시 교체 신호.
그런데 접수는 INSERT 와 커밋 사이에 시간이 걸리고, 그 사이의 반응은 다른 연결에서 **보이지 않는다**. 더 이른 `received_at` 을 가진 반응이 아직 커밋 전이면,
판정이 그것을 모른 채 뒤의 반응을 대표로 굳혀 버린다(최종 데이터에는 더 이른 유효 반응이 있는데도).

그래서 접수와 판정이 **결정 행의 잠금**을 공유한다.
- 접수(`lock_for_receipt`): 트랜잭션 안에서 결정 행을 `FOR UPDATE` 로 잠근 **뒤에** 수신 시각을 정하고 INSERT 한다. 잠금은 커밋까지 간다.
  같은 결정의 접수는 이 잠금으로 줄을 서므로 커밋 순서 = 시각 순서다.
- 판정(`wait_for_inflight_receipts`): 판정을 시작하기 전에 같은 잠금을 한 번 지나간다. 진행 중인 접수가 있으면 그 커밋까지 기다리고, 지나간 뒤에 시작하는 접수는
  (시각이 잠근 뒤에 정해지므로) 이 반응보다 늦은 `received_at` 을 갖는다. 클릭은 표시 교체 신호가 **이후 결정**의 노출이므로 그 결정들(클릭 접수 시각까지, 클릭 기간 안)도 지나간다.

잠금은 결정 단위라 서로 다른 결정의 접수·판정은 막지 않는다. 판정은 잠금을 쥔 채 진행하지 않고(과금 트랜잭션을 길게 막지 않는다) 지나가기만 한다.
잠금 순서는 결정 ID 순으로 고정해 판정끼리 교착하지 않고, 접수는 잠금을 하나만 잡는다.
전제: 서버 시계는 한 방향으로 흐른다(NTP 보정으로 시계가 크게 뒤로 가는 경우는 다루지 않는다).
"""
from django.conf import settings
from django.db import transaction

from .facts import later_decisions
from .models import Decision, Reaction, ReactionStatus, ReactionType


def lock_for_receipt(decision_id):
    """접수 트랜잭션의 **첫 일**: 결정 행을 잠근다(커밋까지). 이 호출 **뒤에** 수신 시각을 정해야 한다. 결정이 없으면 잠글 것이 없다(어차피 거부될 보고다)."""
    list(Decision.objects.select_for_update().filter(pk=decision_id).values_list("pk", flat=True))


def wait_for_inflight_receipts(inbox_id):
    """반응을 판정하기 전에, 이 반응의 판정에 영향을 줄 수 있는 **진행 중인 접수**가 커밋될 때까지 기다린다. 잠금은 바로 놓는다."""
    row = Reaction.objects.filter(pk=inbox_id, status=ReactionStatus.RECEIVED).values("decision_id", "type", "received_at").first()
    if row is None:
        return
    with transaction.atomic():
        decision = Decision.objects.filter(pk=row["decision_id"]).first()
        if decision is None:
            return
        ids = [decision.decision_id]
        click_window = settings.REACTION_CLICK_WINDOW_SECONDS
        if row["type"] == ReactionType.CLICK and (row["received_at"] - decision.decided_at).total_seconds() <= click_window:  # 기간 밖 클릭은 어차피 거부된다
            ids += list(later_decisions(decision).filter(decided_at__lte=row["received_at"]).values_list("decision_id", flat=True))
        list(Decision.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
