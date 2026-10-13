/* 노출 판정은 매체 화면에서 정의한다. 결정마다 최초 유효 관측만 알린다. */
(function (root) {
  "use strict";
  class ImpressionDetector {
    constructor() { this.seen = new Set(); }
    static isRegionVisible({ bounds, region, canvasWidth, canvasHeight, viewportWidth, viewportHeight }) {
      if (bounds.width <= 0 || bounds.height <= 0 || canvasWidth <= 0 || canvasHeight <= 0) return false;
      // Canvas 전체가 잘려도 실제 광고 영역이 온전히 보이면 노출 후보가 된다.
      const scaleX = bounds.width / canvasWidth, scaleY = bounds.height / canvasHeight;
      const left = bounds.left + region.x * scaleX, top = bounds.top + region.y * scaleY;
      return left >= 0 && top >= 0
        && left + region.width * scaleX <= viewportWidth
        && top + region.height * scaleY <= viewportHeight;
    }
    observe({ decisionId, drawn, inZone, visible }) {
      if (!decisionId || !drawn || !inZone || !visible || this.seen.has(decisionId)) return false;
      this.seen.add(decisionId);
      return true;
    }
  }
  root.AdBridgeImpressionDetector = ImpressionDetector;
  if (typeof module !== "undefined") module.exports = ImpressionDetector;
})(globalThis);
