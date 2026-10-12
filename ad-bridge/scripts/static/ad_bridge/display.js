/* 광고 서버가 반환한 이미지와 클릭 주소를 Canvas에 적용한다. */
(function (root) {
  "use strict";
  class AdDisplay {
    constructor() { this.current = null; this.version = 0; }
    async load(decision) {
      const version = ++this.version;
      if (!decision.ad) { this.current = null; return false; }
      const image = new Image();
      // 추가 인증 헤더 없이 공개 이미지 URL을 읽는다. Canvas 픽셀은 읽지 않는다.
      image.referrerPolicy = "no-referrer";
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("광고 이미지를 불러오지 못했습니다."));
        image.src = decision.ad.image_url;
      });
      if (version !== this.version) return false;
      this.current = { decision, image };
      return true;
    }
    draw(context, rect) {
      if (!this.current) return false;
      const image = this.current.image;
      const ratio = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
      const width = image.naturalWidth * ratio, height = image.naturalHeight * ratio;
      context.drawImage(image, rect.x + (rect.width - width) / 2, rect.y + (rect.height - height) / 2, width, height);
      return true;
    }
    click() {
      if (this.current) window.open(this.current.decision.ad.click_url, "_blank", "noopener,noreferrer");
    }
  }
  root.AdBridgeDisplay = AdDisplay;
})(globalThis);
