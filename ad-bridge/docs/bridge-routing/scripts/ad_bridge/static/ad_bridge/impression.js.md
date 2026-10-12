# scripts/ad_bridge/static/ad_bridge/impression.js

원본: `scripts/ad_bridge/static/ad_bridge/impression.js` · [소스 파일](../../../../../../scripts/ad_bridge/static/ad_bridge/impression.js)

AdBridgeImpressionDetector.observe는 decisionId·drawn·inZone·visible을 게임에서 받는다. 모두 유효할 때만 결정별 최초 true를 반환하며 추가 HTTP를 직접 수행하지 않는다. 실제 좌표·포커스·가시성 판단과 보고 호출은 게임이 맡는다.

AdBridgeImpressionDetector.isRegionVisible은 Canvas 좌표의 광고 영역을 화면 좌표로 변환해 광고 영역 전체가 뷰포트 안에 있는지 확인한다. Canvas 전체가 화면에 들어와야 한다는 조건은 사용하지 않는다.

JavaScript는 Python AST 대상이 아니다. Node 검사와 테스트 게임의 실제 브라우저에서 동작을 확인했다.
