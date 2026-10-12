# scripts/ad_bridge/static/ad_bridge/display.js

원본: `scripts/ad_bridge/static/ad_bridge/display.js` · [소스 파일](../../../../../../scripts/ad_bridge/static/ad_bridge/display.js)

AdBridgeDisplay.load는 이미지 로딩 완료 후 결정과 이미지를 교체한다. 실패 시 기존 표시를 유지하며 늦은 로딩은 version으로 무시한다. draw는 비율을 유지해 Canvas에 그리고 click은 반환된 click_url로 새 창을 연다(noopener,noreferrer). Canvas 픽셀을 읽지 않는다.

JavaScript는 Python AST 대상이 아니다. Node 검사와 테스트 게임의 실제 브라우저에서 동작을 확인했다.
