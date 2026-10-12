/* 노출 판정은 매체 화면에서 정의한다. 결정마다 최초 유효 관측만 알린다. */
(function (root) {
  "use strict";
  class ImpressionDetector {
    constructor() { this.seen = new Set(); }
    observe({ decisionId, drawn, inZone, visible }) {
      if (!decisionId || !drawn || !inZone || !visible || this.seen.has(decisionId)) return false;
      this.seen.add(decisionId);
      return true;
    }
  }
  root.AdBridgeImpressionDetector = ImpressionDetector;
  if (typeof module !== "undefined") module.exports = ImpressionDetector;
})(globalThis);
