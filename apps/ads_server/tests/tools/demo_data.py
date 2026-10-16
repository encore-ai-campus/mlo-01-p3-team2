#!/usr/bin/env python
"""광고주 화면 검토용 시연 데이터(Step 6-21, 계획서 §8.4.22). **개발 설정(`config.settings.dev`)에서만** 돈다.

    python tests/tools/demo_data.py     # .env 의 개발 DB 에 시연 광고주·관리자, 매체 하나·구성 셋, 캠페인 넷(집행 중·일시 중지·관리자 중단·종료),
                                        # 광고·소재, 오늘을 포함한 최근 7일의 노출·클릭·전환과 과금을 만든다
    python tests/tools/run_split.py     # 그다음 브라우저로 http://127.0.0.1:8001 — 아이디 USERNAME, 비밀번호 PASSWORD(아래)

모든 것을 앱과 같은 서비스 함수로 만든다(결정 → 반응 → 판정·과금). 시연 계정이 이미 있으면 멈춘다 — 원장은 추가 전용이라 지우지 않는다.
다시 만들려면 개발 DB 를 지우고 `migrate` 한다. 수치·이름은 시안처럼 예시다.
"""
import io
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from random import Random

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

USERNAME, ADMIN_NAME, PASSWORD = "demo", "demo_admin", "Campus-Demo-2026"  # 개발 DB 의 시연 계정(운영과 무관)
DAYS = 7
SHARES = {"impression_share": 90, "click_share": 8, "conversion_share": 2}


def poster(tone):
    """시안의 소재 그림(모래색 바탕 + 원 둘)을 흉내 낸 1200×600 PNG."""
    from PIL import Image, ImageDraw

    accent = {"green": (22, 125, 121), "blue": (71, 127, 160), "walnut": (144, 115, 83)}[tone]
    image = Image.new("RGB", (1200, 600), (232, 210, 172))
    draw = ImageDraw.Draw(image)
    draw.ellipse((780, 30, 1330, 580), fill=accent)
    draw.ellipse((880, 150, 1250, 520), fill=(197, 171, 133))
    draw.rounded_rectangle((70, 470, 430, 540), radius=35, fill=(255, 252, 247))
    out = io.BytesIO()
    image.save(out, format="PNG")
    out.seek(0)
    return out


def main():
    from config.env import load_env

    load_env()
    if os.environ["DJANGO_SETTINGS_MODULE"] != "config.settings.dev":
        raise SystemExit("개발 설정(config.settings.dev)에서만 돈다")
    import django

    django.setup()
    from django.db import transaction
    from django.utils import timezone

    from billing import api as billing
    from campaigns import api as campaigns
    from foundation.models import User
    from masters import api as masters
    from records import api as records
    from records.models import Reaction

    if User.objects.filter(username__in=(USERNAME, ADMIN_NAME)).exists():
        raise SystemExit(f"시연 계정({USERNAME}·{ADMIN_NAME})이 이미 있다 — 다시 만들려면 개발 DB 를 지우고 migrate 한 뒤 실행한다")
    now = timezone.now()
    start = now - timedelta(days=DAYS)
    setup = transaction.atomic()  # 계정·매체·캠페인은 한 번에(중간에 실패하면 아무것도 남지 않는다)
    setup.__enter__()
    admin = User.objects.create_superuser(ADMIN_NAME, PASSWORD, nickname="운영", class_label="-")
    adv = User.objects.create_user(USERNAME, PASSWORD, nickname="이민서", class_label="2반")
    billing.grant_signup(adv, now=start - timedelta(hours=2))  # 가입 지급(기본 50,000)
    billing.adjust(admin, adv.pk, 250_000, "시연 충전", now=start - timedelta(hours=1))

    media = masters.create_media(admin, "PLAYDATA 캠퍼스")
    roof = masters.create_slot(admin, media.media_id, "옥상 광고 게시판", 100, 120, 300, "시연", audience="individual", **SHARES)
    lounge = masters.create_slot(admin, media.media_id, "학습 라운지 전광판", 100, 150, 400, "시연", audience="shared", **SHARES)
    lobby = masters.create_slot(admin, media.media_id, "로비 배너", 100, 110, 250, "시연", audience="individual", **SHARES)

    def campaign(name, ends, budget, slot, bid, ad_name, tone, when=start):
        c = campaigns.create_campaign(adv, name, when, ends, budget, now=when)
        g = campaigns.create_ad_group(adv, c.campaign_id, ad_name, [slot.slot_id], bid_amount=bid, now=when)
        campaigns.create_creative(adv, g.ad_group_id, f"{name} · 배너 01", "https://example.com/campus", poster(tone), now=when)
        return c

    fall = campaign("가을 캠퍼스 프로그램", now + timedelta(days=17), 15_000, roof, 120, "옥상 게시판 · 가을 과정", "green")
    event = campaign("학습 라운지 이벤트", None, 10_000, lounge, 150, "라운지 전광판 · 이벤트", "blue")
    notice = campaign("신규 과정 안내", now + timedelta(days=16), 8_000, lobby, 110, "로비 배너 · 신규 과정", "walnut")
    summer_start = now - timedelta(days=75)
    summer = campaign("여름 캠퍼스 프로그램", now - timedelta(days=45), 12_000, lobby, 100, "로비 배너 · 여름 과정", "green", when=summer_start)
    campaigns.end_expired_campaigns(now=now)  # 기간이 지난 여름 캠페인을 ENDED 로(주기 작업과 같은 함수)
    setup.__exit__(None, None, None)

    rng = Random(618)
    counts = {"decisions": 0, "impressions": 0, "clicks": 0, "conversions": 0}
    plan = ((roof, 115), (lounge, 70), (lobby, 45))  # (구성, 하루 결정 수 어림)
    for day in range(DAYS, -1, -1):
        base = now - timedelta(days=day)
        window = (now - base.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() if day == 0 else 86_400
        for slot, per_day in plan:
            n = int(per_day * (0.75 + 0.5 * rng.random()) * (window / 86_400 if day == 0 else 1))
            for _ in range(n):
                at = base - timedelta(seconds=rng.uniform(0, window - 10)) if day == 0 else base.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=rng.uniform(0, window - 10))
                person = str(uuid.UUID(int=rng.getrandbits(128), version=4))  # 개인 구성은 결정의 subject, 일괄 구성은 클릭·전환의 viewer
                subject = person if slot.audience == "individual" else None
                decision = records.decide(slot.media_id, slot.slot_id, subject_id=subject, now=at, rng=rng)
                counts["decisions"] += 1
                if decision.chosen is None:
                    continue
                seen = at + timedelta(seconds=1)
                view, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", seen, {}, subject_id=subject, now=seen)
                if records.process_reaction(view.inbox_id, now=seen) == "ACCEPTED":
                    counts["impressions"] += 1
                if rng.random() < 0.026:
                    clicked = at + timedelta(seconds=2)
                    records.observe_click(decision.decision_id, None if subject else person, now=clicked)
                    click = Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK").first()
                    if click is None:
                        continue
                    records.process_reaction(click.inbox_id, now=clicked)
                    counts["clicks"] += 1
                    if rng.random() < 0.25:
                        done = at + timedelta(seconds=3)
                        conv, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "CONVERSION", done, {}, subject_id=person, now=done)
                        records.process_reaction(conv.inbox_id, now=done)
                        counts["conversions"] += 1

    campaigns.update_campaign(adv, event.campaign_id, {"status": "PAUSED"}, now=now - timedelta(hours=1))
    campaigns.suspend_campaign(admin, notice.campaign_id, "소재 문구가 광고 기준(과장 표현)에 맞지 않습니다", now=now - timedelta(minutes=30))
    wallet = billing.get_wallet(adv)
    print(f"시연 데이터: 캠페인 4(집행 중 {fall.name} · 일시 중지 {event.name} · 관리자 중단 {notice.name} · 종료 {summer.name}), "
          f"결정 {counts['decisions']} · 노출 {counts['impressions']} · 클릭 {counts['clicks']} · 전환 {counts['conversions']}, 잔액 {wallet.balance:,} 포인트")
    print(f"로그인: 아이디 {USERNAME}(비밀번호는 이 파일의 PASSWORD)")


if __name__ == "__main__":
    main()
