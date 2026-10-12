# scripts/ad_bridge/results/service.py

원본: `scripts/ad_bridge/results/service.py` · [소스 파일](../../../../../scripts/ad_bridge/results/service.py)

사용자 소유의 접수 완료 노출을 읽고 GET 결과의 ID·사용자·종류·발생 시각을 대조한 뒤 판정 저장을 호출한다. 통신·DB 오류는 호출자에게 전달하며 PUT을 수행하지 않는다.

## 직접 선언

### refresh_result

참조: `scripts/ad_bridge/results/service.py::def refresh_result(*, client, store, decision_id: str | UUID, subject_id: str | UUID) -> StoredImpression`

게임 서버의 로그인 사용자 UUID로 조회한다. 실패는 호출자에게 전달한다.
