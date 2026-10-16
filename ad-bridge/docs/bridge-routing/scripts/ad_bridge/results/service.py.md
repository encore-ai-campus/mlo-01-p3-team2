# ad-bridge/scripts/results/service.py

원본: `ad-bridge/scripts/results/service.py` · [소스 파일](../../../../../scripts/results/service.py)

owner_id로 사용자 소유의 접수 완료 노출을 읽고 GET 결과의 ID·저장된 광고 가명·종류·발생 시각을 대조한 뒤 판정 저장을 호출한다. 판정 저장의 권한 검사에도 같은 owner_id를 전달한다. 현재 비밀로 가명을 다시 계산하지 않는다. 통신·DB 오류는 호출자에게 전달하며 PUT을 수행하지 않는다.

## 직접 선언

### refresh_result

참조: `ad-bridge/scripts/results/service.py::def refresh_result(*, client, store, decision_id: str | UUID, owner_id: str | UUID) -> StoredImpression`

게임 서버의 로그인 사용자 UUID인 owner_id로 접근 권한을 확인한다. 광고 서버의 결과 subject_id는 발급 당시 저장한 가명과 대조한다. 실패는 호출자에게 전달한다.
