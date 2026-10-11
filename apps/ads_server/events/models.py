"""이벤트 outbox(설계 §6.3, DRD P3). 결정·접수·판정·과금이 저장되는 **같은 트랜잭션**에서 한 줄씩 쓰고, 중계(`relay_events`)가 MongoDB 로 옮긴 뒤 `sent_at` 을 채운다."""
import uuid

from django.db import models
from django.utils import timezone


class EventOutbox(models.Model):
    # PK = 이벤트 ID. **원천 ID 와 이벤트 종류에서 결정적으로** 만든다(events.schemas.event_id_of) → 재처리·재전송에도 같은 값이고,
    # 같은 이벤트를 두 번 쓰려 해도 PK 가 막아 한 줄만 남는다. 시각순이 아니라서(UUIDv5) 쓰기 위치는 흩어지지만 이 표는 보낸 뒤 비워지는 대기열이다.
    event_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    event_name = models.CharField(max_length=64)  # 예: ad.decision. Debezium outbox 라우터의 type 에 대응
    schema_version = models.PositiveSmallIntegerField()
    aggregate_id = models.UUIDField()  # 메시지 키 = decision_id (DRD §5.6). Debezium 의 aggregateid 에 대응
    payload = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)  # 이벤트의 produced_at: outbox 에 쓴 시각
    sent_at = models.DateTimeField(null=True, blank=True)  # 비어 있으면 아직 안 보냈다. 중계는 "마지막 번호 이후"가 아니라 이 열이 빈 행을 보낸다(늦게 커밋된 행을 건너뛰지 않으려고)

    class Meta:
        db_table = "events_outbox"
        indexes = [
            models.Index(fields=["sent_at", "created_at"], name="events_outbox_pending_idx"),
            models.Index(fields=["event_name", "created_at"], name="events_outbox_name_created_idx"),  # 구간 manifest 가 종류·창마다 그 범위만 읽는다(외부 검토 7936ac7 P3-3)
        ]
