# ad-bridge/scripts/migrations/0003_decision_owner.py

원본: `ad-bridge/scripts/migrations/0003_decision_owner.py` · [원본 파일](../../../../../scripts/migrations/0003_decision_owner.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../../scripts/README.md)

## 역할

IssuedDecision에 게임 내부 소유자 UUID인 owner_id를 추가한다. 0002_impression_retry 다음에 적용한다. 기존 결정의 owner_id는 None으로 남기며 광고 subject_id에서 소유자를 자동 추정하지 않는다. 기존 결정과 노출의 ID·가명·발생 시각·전송 상태·일정·임대를 변경하지 않는다.

## 직접 선언

참조: `ad-bridge/scripts/migrations/0003_decision_owner.py::class Migration(migrations.Migration)`

AST에서 확인한 호출 표기는 migrations.AddField와 models.UUIDField다. 데이터 변환 함수는 선언하지 않는다.

## 검증 범위

클래스 선언과 호출 표기는 routing-doc-sync AST 결과를 사용한다. 0002 상태의 원본 UUID 기반 기록과 가명 기반 기록을 생성한 뒤 0003을 적용하는 임시 DB 검사에서, owner_id만 None으로 추가되고 기존 결정·노출 내용은 유지되는 것을 확인했다. 실제 게임 DB에는 이번 작업에서 적용하지 않았다.
