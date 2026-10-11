# 구현할 작업

- [ ] **연결 설정:** 광고 서버 주소·`X-Media-Key`·타임아웃 설정. [관련 규칙](./ads-api-integration-rules.md#지켜야-할-규칙)
- [ ] **광고 요청:** `create_decision()`으로 광고를 요청하고 광고 정보·`decision_id` 받기. [관련 규칙](./ads-api-integration-rules.md#지켜야-할-규칙)
- [ ] **반응 보고:** `put_reaction()`으로 전달받은 노출·전환 정보를 보내고 접수 응답 받기. [관련 규칙](./ads-api-integration-rules.md#지켜야-할-규칙)
- [ ] **결과 조회:** `get_reaction()`으로 최종 인정·거부 결과 받기. [관련 규칙](./ads-api-integration-rules.md#지켜야-할-규칙)
- [ ] **오류·재시도:** 연결 실패·타임아웃·오류 응답 처리, 같은 반응 ID·본문으로 재시도. [관련 규칙](./ads-api-integration-rules.md#지켜야-할-규칙)
