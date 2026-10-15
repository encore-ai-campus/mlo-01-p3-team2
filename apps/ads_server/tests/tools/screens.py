#!/usr/bin/env python
"""광고주 화면을 시안과 나란히 보는 캡처(Step 6-21, 계획서 §8.4.22). 개발용 — `run_split.py` 로 띄운 로컬 서버와 `demo_data.py` 의 시연 계정이 필요하다.

    python tests/tools/screens.py OUT                         # OUT/<화면>.png (1440 폭, 시안 높이)
    python tests/tools/screens.py OUT --design DIR            # + OUT/compare-<화면>.png: 왼쪽 시안(DIR/screens/<키>.png), 오른쪽 지금 화면
    python tests/tools/screens.py OUT --only dashboard,points

프론트(기본 http://127.0.0.1:8001)에 시연 계정으로 로그인해 화면 HTML 을 받고, 정적 파일은 이 저장소의 파일로, 로그인해야 받는 그림은 받아 둔 파일로 바꿔
headless Chrome 으로 찍는다(브라우저에 쿠키를 넣지 않아도 된다). 표준 라이브러리 + Pillow 만 쓴다.
"""
import argparse
import hashlib
import html
import http.cookiejar
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
STATIC = TOOLS.parents[2] / "ads_frontend/ui/static"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# (이름, 시안 키, 높이) — 경로는 아래 pages() 가 시연 데이터에서 찾는다
SCREENS = [("login", "login", 1024), ("signup", "signup", 1024), ("dashboard", "dashboard", 1110), ("campaigns", "campaigns", 1024),
           ("campaign-detail", "campaign-detail", 1024), ("suspended", "suspended", 1024), ("campaign-create", "campaign-create", 1024),
           ("ad-create", "ad-create", 1700), ("ad-create-filled", "ad-create", 1700), ("ad-detail", "ad-detail", 1120), ("creatives", "creatives", 1080), ("creative-detail", "creative-detail", 1024), ("points", "points", 1024),
           ("account", "account", 1024)]


class Site:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path):
        with self.opener.open(self.base + path, timeout=30) as r:  # nosec B310 — 로컬 개발 서버(인자로 받은 주소)
            return r.read(), r.headers.get_content_type(), r.geturl()

    def login(self, username, password):
        page = self.get("/accounts/login/")[0].decode()
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
        data = urllib.parse.urlencode({"csrfmiddlewaretoken": token, "username": username, "password": password}).encode()
        request = urllib.request.Request(self.base + "/accounts/login/", data=data, headers={"Referer": self.base + "/accounts/login/"})
        with self.opener.open(request, timeout=30) as r:  # nosec B310
            if "/accounts/login/" in r.geturl():
                raise SystemExit("로그인 실패 — demo_data.py 로 시연 계정을 만들었는지 확인")

    def post(self, path, data):
        request = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data, doseq=True).encode(), headers={"Referer": self.base + path})
        with self.opener.open(request, timeout=30) as r:  # nosec B310
            return r.read(), r.headers.get_content_type(), r.geturl()


def filled_ad_create(site, path):
    """광고 만들기에 값을 채우고 '구성별 적용금액 계산'을 누른 화면(시안 ad-create 와 같은 상태). 저장하지 않는다(action=preview)."""
    page = site.get(path)[0].decode()
    find = lambda pattern: re.search(pattern, page, re.S).group(1)
    return site.post(path, {
        "csrfmiddlewaretoken": find(r'name="csrfmiddlewaretoken" value="([^"]+)"'), "request_key": find(r'name="request_key" value="([^"]+)"'),
        "campaign_id": find(r'name="campaign_id"[^>]*>\s*<option value="([^"]+)"'), "group_name": "옥상 게시판 · 가을 과정",
        "slot_ids": find(r'value="([0-9a-f-]{36})">\s*<span class="name">옥상'), "bid_amount": "120",
        "creative_source": "existing", "creative_id": find(r'name="creative_id".*?<option value="([0-9a-f-]{36})"'), "action": "preview",
    })[0].decode()


def pages(site):
    """시연 데이터에서 상세 화면의 경로를 찾는다."""
    found = {"dashboard": "/advertiser/", "campaigns": "/advertiser/campaigns/", "campaign-create": "/advertiser/campaigns/new/",
             "ad-create": "/advertiser/ads/new/", "ad-create-filled": "/advertiser/ads/new/", "creatives": "/advertiser/creatives/", "points": "/advertiser/points/", "account": "/advertiser/me/"}
    listing = site.get(found["campaigns"])[0].decode()
    for key, name in (("campaign-detail", "가을 캠퍼스 프로그램"), ("suspended", "신규 과정 안내")):
        match = re.search(r'href="(/advertiser/campaigns/[0-9a-f-]{36}/)"[^>]*>(?:<[^>]+>)*\s*' + re.escape(name), listing)
        if match:
            found[key] = match.group(1)
    match = re.search(r'href="(/advertiser/creatives/[0-9a-f-]{36}/)"', site.get(found["creatives"])[0].decode())
    if match:
        found["creative-detail"] = match.group(1)
    if "campaign-detail" in found:
        detail = site.get(found["campaign-detail"])[0].decode()
        match = re.search(r'href="(/advertiser/ad-groups/[0-9a-f-]{36}/)"', detail)
        if match:
            found["ad-detail"] = match.group(1)
    return found


def localize(site, page, out):
    """정적 파일은 저장소 파일로, 그 밖의 같은 사이트 그림(로그인해야 받는 소재 그림)은 받아 OUT/files 에 둔다."""
    files = out / "files"
    files.mkdir(exist_ok=True)

    def asset(match):
        attr, url = match.group(1), html.unescape(match.group(2))
        if url.startswith("/static/"):
            return f'{attr}="{(STATIC / url[len("/static/"):].split("?")[0]).as_uri()}"'
        if url.startswith("/") and not url.startswith("//"):
            body, kind, _ = site.get(url)
            if kind.startswith("image/"):
                name = hashlib.sha256(url.encode()).hexdigest()[:16] + "." + kind.split("/")[1]
                (files / name).write_bytes(body)
                return f'{attr}="{(files / name).as_uri()}"'
        return match.group(0)

    return re.sub(r'(src|href)="([^"]+)"', asset, page)


def shoot(page_file, png, height):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files", "--force-device-scale-factor=1",
                    f"--window-size=1440,{height}", "--virtual-time-budget=3000", f"--screenshot={png}", page_file.as_uri()],
                   check=True, capture_output=True, timeout=60)


def compare(design_png, shot_png, out_png):
    from PIL import Image, ImageDraw

    left, right = Image.open(design_png).convert("RGB"), Image.open(shot_png).convert("RGB")
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width + 24, height + 36), (255, 255, 255))
    canvas.paste(left, (0, 36))
    canvas.paste(right, (left.width + 24, 36))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 10), "시안", fill=(0, 0, 0))
    draw.text((left.width + 32, 10), "지금 화면", fill=(0, 0, 0))
    canvas.save(out_png)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--design", type=Path, help="시안 폴더(screens/<키>.png 가 있는 곳)")
    parser.add_argument("--only", help="쉼표로 구분한 화면 이름")
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    options = parser.parse_args()
    sys.path.insert(0, str(TOOLS))
    from demo_data import PASSWORD, USERNAME

    out = options.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(options.only.split(",")) if options.only else None
    anonymous, site = Site(options.base), Site(options.base)
    site.login(USERNAME, PASSWORD)
    paths = {"login": "/accounts/login/", "signup": "/accounts/signup/", **pages(site)}
    for name, key, height in SCREENS:
        if (wanted and name not in wanted) or name not in paths:
            continue
        client = anonymous if name in ("login", "signup") else site
        body = filled_ad_create(site, paths[name]) if name == "ad-create-filled" else client.get(paths[name])[0].decode()
        page = localize(client, body, out)
        page_file = out / f"{name}.html"
        page_file.write_text(page, encoding="utf-8")
        png = out / f"{name}.png"
        shoot(page_file, png, height)
        line = f"{name:16} {paths[name]} → {png.name}"
        if options.design and (options.design / "screens" / f"{key}.png").exists():
            compare(options.design / "screens" / f"{key}.png", png, out / f"compare-{name}.png")
            line += f" · compare-{name}.png"
        print(line)


if __name__ == "__main__":
    main()
