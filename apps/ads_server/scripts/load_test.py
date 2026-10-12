#!/usr/bin/env python
"""Step 2-6 동시성 검증(설계 §6.5-8): 150개 동시 결정·150개 동시 반응을 실제 HTTP 로 보내고 **불변식**을 확인한다.

    python scripts/load_test.py            # 150 동시(기본)
    python scripts/load_test.py --small    # 20 동시(몇 초)
    python scripts/load_test.py --json out.json

환경: **MySQL 8.4**(실행마다 새 `ads_load_*` 데이터베이스를 만들고 끝나면 지운다), 실제 미들웨어를 거치는 스레드형 WSGI 서버
(파이썬 표준 `wsgiref` — 운영용 서버가 아니다), 별도 프로세스로 뜨는 `process_reactions`. 클라이언트는 계약의 재시도 규칙을 따른다
(429·503·연결 실패는 `Retry-After` 를 지켜 같은 요청을 다시 보낸다). 개발 DB 는 건드리지 않는다.

확인하는 것(종료 코드 0 = 모두 충족):
  1. 수신 확인(2xx)한 결정·반응은 전부 저장돼 있다(유실 0). 저장 실패(503)를 받은 요청은 저장되지 않았다.
  2. 같은 반응은 한 번만 과금된다(이중 과금 0). 같은 결정·유형은 하나만 인정된다.
  3. 인정된 반응의 과금 건수·금액이 원장과 맞고, 잔액 = 원장 합계, 일 소진액 = 원장의 그날 과금 합이다.
  4. 처리가 끝나면 `RECEIVED` 가 남지 않는다. SIGTERM 은 현재 반응만 끝내고 멈추며 재기동 뒤 이어서 처리된다.

한계(결과 해석 때 함께 읽는다): 서버와 클라이언트가 한 프로세스(GIL 공유)라 지연 시간은 실제 배포보다 나쁘게 나오고, 단일 서버 프로세스라
다중 워커(프로세스별 요청 제한 버킷)는 검증하지 않는다. 처리량 수치는 이 장비·이 서버 구성의 값이다.
"""
import argparse
import http.client
import json
import math
import os
import random
import shutil
import signal
import socketserver
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

BASE_DIR = Path(__file__).resolve().parent.parent
RETRYABLE = (0, 429, 503)


# ---------------------------------------------------------------- 불변식 검사 (Django 가 설정된 프로세스에서 호출)

def verify_invariants(acked_decisions=(), acked_reactions=None, expect_drained=True, quiescent=False):
    """저장소가 약속을 지켰는지 확인한다. 어긋난 곳의 설명 목록(지키면 빈 목록).

    quiescent: 이미 열린 트랜잭션 안(단위 시험)에서 부를 때만 True — 동시에 쓰는 연결이 없다는 호출자의 보장(`billing.check_ledger` 참고). 부하 시험 본체는 트랜잭션 밖에서 부른다.
    acked_decisions: 수신 확인(201)한 결정 ID 들.
    acked_reactions: {(매체 ID, reaction_id): (결정 ID, 유형)} — 수신 확인한 반응의 **연결**. 저장된 행이 같은 매체·같은 결정·같은 유형인지 대조한다.
    """
    from collections import defaultdict
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from billing import api as billing
    from billing.budget_day import budget_day_of
    from billing.models import CampaignSpend, LedgerEntry
    from records.models import Decision, Reaction

    problems = []
    decisions = {str(d.decision_id): d for d in Decision.objects.all()}
    lost = {str(i) for i in acked_decisions} - decisions.keys()
    if lost:
        problems.append(f"수신 확인한 결정 {len(lost)}건이 저장돼 있지 않다(유실)")

    reactions = list(Reaction.objects.all())
    by_reaction_id = {}
    for r in reactions:
        by_reaction_id.setdefault((str(r.media_id), str(r.reaction_id)), []).append(r)
    if any(len(rows) > 1 for rows in by_reaction_id.values()):
        problems.append("같은 (매체, reaction_id) 가 둘 이상 저장돼 있다")
    lost = relinked = retyped = 0
    for (media_id, reaction_id), (decision_id, reaction_type) in (acked_reactions or {}).items():
        rows = by_reaction_id.get((str(media_id), str(reaction_id)))
        if not rows:
            lost += 1
            continue
        if str(rows[0].decision_id) != str(decision_id):
            relinked += 1
        if rows[0].type != reaction_type:
            retyped += 1
    if lost:
        problems.append(f"수신 확인한 반응 {lost}건이 저장돼 있지 않다(유실)")
    if relinked:
        problems.append(f"수신 확인한 반응 {relinked}건이 확인한 것과 다른 결정에 연결돼 있다")
    if retyped:
        problems.append(f"수신 확인한 반응 {retyped}건의 유형이 확인한 것과 다르다")

    accepted = [r for r in reactions if r.status == "ACCEPTED"]
    seen = {}
    for r in accepted:
        seen[(r.decision_id, r.person_id, r.type)] = seen.get((r.decision_id, r.person_id, r.type), 0) + 1
    if any(count > 1 for count in seen.values()):
        problems.append("같은 결정·사람·유형이 두 번 이상 인정됐다")
    # 퍼널: 인정된 클릭은 서버가 관측한 것이고, **도착 시각**으로 앞 단계가 맞아야 한다 — 클릭은 같은 사람의 인정된 노출이 클릭 접수 + 보류 기한 안에,
    # 전환은 같은 사람의 인정된 클릭이 전환 접수 시각까지 도착했어야 한다(처리 시각이 아니라 도착 시각: 처리가 늦어도 정상이고 기한 뒤의 도착은 소급되지 않는다)
    arrivals = defaultdict(list)
    for r in accepted:
        arrivals[(str(r.decision_id), r.person_id, r.type)].append(r.received_at)
    hold = timedelta(seconds=settings.REACTION_HOLD_SECONDS)
    funnel = {"media_click": 0, "no_impression": 0, "late_impression": 0, "no_click": 0, "click_after_conversion": 0, "click_late": 0, "conversion_late": 0}
    for r in accepted:
        key = (str(r.decision_id), r.person_id)
        if r.type == "CLICK":
            funnel["media_click"] += r.source != "server"
            impressions = arrivals.get((*key, "IMPRESSION"), [])
            funnel["no_impression"] += not impressions
            funnel["late_impression"] += bool(impressions) and min(impressions) > r.received_at + hold
            decision = decisions.get(str(r.decision_id))
            funnel["click_late"] += bool(decision) and r.received_at > decision.decided_at + timedelta(seconds=settings.REACTION_CLICK_WINDOW_SECONDS)
        elif r.type == "CONVERSION":
            clicks = arrivals.get((*key, "CLICK"), [])
            funnel["no_click"] += not clicks
            funnel["click_after_conversion"] += bool(clicks) and min(clicks) > r.received_at
            before = [c for c in clicks if c <= r.received_at]
            funnel["conversion_late"] += bool(before) and r.received_at > max(before) + timedelta(seconds=settings.REACTION_CONVERSION_WINDOW_SECONDS)
    funnel_labels = {
        "media_click": "매체가 보고한 클릭이 인정됐다", "no_impression": "노출 없이 클릭이 인정됐다", "no_click": "클릭 없이 전환이 인정됐다",
        "late_impression": "클릭 접수 + 보류 기한 뒤에야 도착한 노출로 클릭이 인정됐다", "click_after_conversion": "전환보다 늦게 생긴 클릭으로 전환이 인정됐다",
        "click_late": "클릭 기간(결정 후)을 넘긴 클릭이 인정됐다", "conversion_late": "클릭 후 전환 기간을 넘긴 전환이 인정됐다",
    }
    problems += [f"{funnel_labels[key]}: {count}건" for key, count in funnel.items() if count]

    expected_refs = set()
    for r in accepted:
        decision = decisions.get(str(r.decision_id))
        if decision is None or decision.creative_id is None:
            problems.append(f"근거 없는 결정에 대한 반응이 인정됐다: {r.reaction_id}")
        elif r.type == decision.pricing_unit:
            expected_refs.add(f"{r.media_id}:{r.reaction_id}")
    charges = list(LedgerEntry.objects.filter(entry_type="CHARGE").select_related("wallet"))
    refs = [c.reaction_ref for c in charges]
    if len(refs) != len(set(refs)):
        problems.append("같은 반응이 두 번 과금됐다(이중 과금)")
    by_ref = {f"{r.media_id}:{r.reaction_id}": r for r in accepted}
    wrong = {"owner": 0, "campaign": 0, "amount": 0, "shortfall": 0, "time": 0, "policy": 0}
    for charge in charges:  # 각 과금을 **결정에 기록된 근거**와 대조한다(원장 안의 수치만 맞는 것으로는 부족하다)
        reaction = by_ref.get(charge.reaction_ref)
        decision = decisions.get(str(reaction.decision_id)) if reaction else None
        if decision is None:
            continue  # 아래의 '인정되지 않은 반응에 대한 과금'이 잡는다
        wrong["owner"] += charge.wallet.owner_id != decision.owner_id
        wrong["campaign"] += charge.campaign_id != decision.campaign_id
        wrong["amount"] += not (charge.amount <= 0 and -charge.amount + charge.shortfall == decision.applied_amount)  # 받은 금액 + 부족분 = 적용 금액
        wrong["shortfall"] += bool(charge.shortfall) and charge.balance_after != 0  # 부족분은 잔액을 다 받았을 때만 생긴다
        wrong["time"] += charge.created_at != reaction.received_at
        wrong["policy"] += charge.charge_policy != settings.BILLING_CHARGE_POLICY
    labels = {
        "owner": "과금 대상 광고주가 결정의 광고주와 다르다", "campaign": "과금의 캠페인이 결정의 캠페인과 다르다",
        "amount": "과금액(+부족분)이 결정의 적용 금액과 다르다", "shortfall": "잔액이 남았는데 부족분이 기록됐다",
        "time": "과금 시각이 반응의 접수 시각과 다르다", "policy": "과금 정책 이름이 설정과 다르다",
    }
    problems += [f"{labels[key]}: {count}건" for key, count in wrong.items() if count]
    missing, orphans = expected_refs - set(refs), set(refs) - expected_refs
    if missing:
        problems.append(f"인정된 반응 {len(missing)}건에 과금이 없다")
    if orphans:
        problems.append(f"인정되지 않은 반응에 대한 과금 {len(orphans)}건")

    problems += billing.check_ledger(quiescent=quiescent)  # 잔액 = 원장 합계, balance_after·seq 연속
    per_day = {}
    for c in charges:
        key = (c.campaign_id, budget_day_of(c.created_at))
        per_day[key] = per_day.get(key, 0) - c.amount
    spend = {(s.campaign_id, s.budget_day): s.spent for s in CampaignSpend.objects.all()}
    if {k: v for k, v in per_day.items() if v} != {k: v for k, v in spend.items() if v}:
        problems.append("일 소진액이 원장의 그날 과금 합과 다르다")

    if expect_drained:
        # 앞 단계(노출·클릭)를 기다리는 보류는 기한(REACTION_HOLD_SECONDS) 안에서는 정상이다. 그 밖의 RECEIVED 는 처리되지 않은 것이다
        now = timezone.now()
        hold = timedelta(seconds=settings.REACTION_HOLD_SECONDS + settings.REACTION_HOLD_RECHECK_SECONDS)
        stale = sum(1 for r in reactions if r.status == "RECEIVED" and not (r.type != "IMPRESSION" and now - r.received_at <= hold))
        if stale:
            problems.append(f"처리되지 않은 반응(RECEIVED) {stale}건이 남아 있다")
    return problems


class LagSampler(threading.Thread):
    """이벤트가 outbox 에서 **처음 보인 시각 − 생성 시각(produced_at)** 을 잰다 = 생성 시각을 잡은 뒤 커밋돼 보이기까지의 지연(설계 §10 H11).
    구간별 정합 manifest 의 창 닫힘 여유(`EVENTS_HOP_GRACE_SECONDS`, 기본 120초)가 이 지연의 상한보다 큰지 확인하는 증거다.
    주기적으로 최근 `horizon` 초의 이벤트를 훑어 처음 보인 시각을 기록한다(자기 연결을 쓴다). 끝나고 `report()` 가 한 번도 못 본 이벤트까지 센다."""

    def __init__(self, interval=0.3, horizon=150.0):
        super().__init__(daemon=True)
        self.interval, self.horizon, self.seen, self.stop_event = interval, horizon, {}, threading.Event()
        self.started = None

    def run(self):
        from django.db import connection
        from django.utils import timezone

        from events.models import EventOutbox

        self.started = timezone.now()
        while not self.stop_event.is_set():
            try:
                polled = timezone.now()
                for event_id, created_at in EventOutbox.objects.filter(created_at__gte=polled - timedelta(seconds=self.horizon)).values_list("event_id", "created_at"):
                    if event_id not in self.seen:
                        self.seen[event_id] = (polled - created_at).total_seconds()
            except Exception:  # noqa: BLE001 — DB 가 끊긴 순간은 건너뛴다(장애 시험)
                connection.close()
            self.stop_event.wait(self.interval)
        connection.close()

    def stop(self):
        self.stop_event.set()
        self.join(timeout=10)

    def report(self, grace_seconds):
        """{"events", "max_lag_s", "late", "unobserved"}. `late`: 지연이 여유보다 컸던 이벤트, `unobserved`: 훑는 범위 안에서 한 번도 못 본 이벤트(= 지연이 훑는 범위보다 컸다)."""
        from django.conf import settings  # noqa: F401
        from events.models import EventOutbox

        every = set(EventOutbox.objects.filter(created_at__gte=self.started - timedelta(seconds=5)).values_list("event_id", flat=True))
        lags = list(self.seen.values())
        return {"events": len(every), "max_lag_s": round(max(lags), 3) if lags else 0.0, "late": sum(1 for lag in lags if lag > grace_seconds), "unobserved": len(every - self.seen.keys())}


def _differing_keys(stored, wanted):
    keys = sorted(k for k in set(stored) | set(wanted) if json.dumps(stored.get(k), sort_keys=True, default=str) != json.dumps(wanted.get(k), sort_keys=True, default=str))
    return keys or ["(타입)"]  # 값의 JSON 모양은 같고 타입만 다른 경우


def verify_events(relayed=False):
    """이벤트 검증(Step 4). 어긋난 곳의 설명 목록(맞으면 빈 목록).

    ① 원본 행 ↔ outbox: 이벤트가 **정확히 하나**씩 있고(빠짐·남음), 내용(이벤트 이름·메시지 키·**봉투의 스키마 버전·생성 시각**·**페이로드 전체**)이 원본 행에서 다시 만든 것과 JSON 타입까지 같다.
    ② `relayed`(중계가 모두 끝난 시점): 미전송 0, MongoDB 의 ID 집합 = outbox, 그리고 **MongoDB 문서 전체(봉투 + 페이로드)가 outbox 와 같다**.
    outbox 와 MongoDB 를 같은 잘못된 값으로 바꿔도 ①이 잡고, MongoDB 만 바꿔도 ②가 잡는다.
    """
    from events import relay, schemas, store
    from events.models import EventOutbox

    from records.api import expected_events

    expected = expected_events()
    outbox = {row.pk: row for row in EventOutbox.objects.all()}
    problems = []
    if expected.keys() - outbox.keys():
        problems.append(f"이벤트가 없는 원본 행 {len(expected.keys() - outbox.keys())}건")
    if outbox.keys() - expected.keys():
        problems.append(f"원본 행이 없는 이벤트 {len(outbox.keys() - expected.keys())}건")
    wrong = {}
    for event_id in expected.keys() & outbox.keys():
        name, key, produced_at, payload = expected[event_id]
        row = outbox[event_id]
        envelope = {"schema_version": (row.schema_version, schemas.SCHEMA_VERSION), "produced_at": (row.created_at, produced_at)}
        bad_envelope = [k for k, (got, want) in envelope.items() if got != want]
        if (row.event_name, row.aggregate_id) != (name, key) or bad_envelope or not relay.same_document({"p": row.payload}, {"p": payload}):
            wrong.setdefault(name, []).append((event_id, bad_envelope + (_differing_keys(row.payload, payload) if not relay.same_document({"p": row.payload}, {"p": payload}) else [])))
    for name, items in sorted(wrong.items()):
        problems.append(f"원본 행과 내용이 다른 {name} 이벤트 {len(items)}건 (예: {items[0][0]} 의 {items[0][1]})")
    if relayed:
        unsent = sum(1 for row in outbox.values() if row.sent_at is None)
        if unsent:
            problems.append(f"MongoDB 로 보내지 않은 이벤트 {unsent}건이 남아 있다")
        in_mongo = {d["_id"]: d for d in store.collection().find()}
        if in_mongo.keys() != outbox.keys():
            problems.append(f"MongoDB 의 이벤트가 outbox 와 다르다(없음 {len(outbox.keys() - in_mongo.keys())}건, 더 있음 {len(in_mongo.keys() - outbox.keys())}건)")
        different = [i for i in in_mongo.keys() & outbox.keys() if not relay.same_document(in_mongo[i], relay.to_document(outbox[i]))]
        if different:
            doc, want = in_mongo[different[0]], relay.to_document(outbox[different[0]])
            problems.append(f"MongoDB 문서가 outbox 와 내용이 다른 이벤트 {len(different)}건 (예: {different[0]} 의 {_differing_keys(doc.get('payload', {}), want['payload']) if doc.get('payload') != want['payload'] else '봉투'})")
    return problems


# ---------------------------------------------------------------- HTTP 클라이언트 (계약의 재시도 규칙)

class Outcome:
    def __init__(self, status, body, headers, latency, total, attempts):
        self.status, self.body, self.headers = status, body, headers
        self.latency, self.total, self.attempts = latency, total, attempts  # 마지막 시도 / 재시도 포함 전체 / 시도별 상태

    @property
    def acked(self):
        return self.status in (200, 201)


def call(port, method, path, key, body=None, retry=True, give_up_after=90):
    started, attempts = time.perf_counter(), []
    while True:
        t0 = time.perf_counter()
        status, data, headers = 0, None, {}
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            headers_out = {"Content-Type": "application/json"}
            if key is not None:  # 클릭 주소(`/c/`)는 인증이 없다
                headers_out["X-Media-Key"] = key
            conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers_out)
            response = conn.getresponse()
            raw = response.read()
            status, headers = response.status, {k.lower(): v for k, v in response.getheaders()}
            data = json.loads(raw) if raw else None
            conn.close()
        except (OSError, ValueError):
            status = 0
        latency = time.perf_counter() - t0
        attempts.append(status)
        if status not in RETRYABLE or not retry or time.perf_counter() - started > give_up_after:
            return Outcome(status, data, headers, latency, time.perf_counter() - started, attempts)
        wait = float(headers.get("retry-after", 0.2)) if status in (429, 503) else 0.2
        time.sleep(wait * (1 + random.random() * 0.5))  # 지터


def run_concurrent(count, work):
    """`work(i)` 를 스레드 `count` 개로 **동시에 시작**한다. 결과 목록을 돌려준다."""
    barrier, results, errors = threading.Barrier(count), [None] * count, []

    def worker(i):
        try:
            barrier.wait(timeout=60)
            results[i] = work(i)
        except Exception as error:  # noqa: BLE001
            errors.append(repr(error))

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    [t.start() for t in threads]
    [t.join(timeout=300) for t in threads]
    if errors:
        raise RuntimeError(f"작업자 오류: {errors[:3]}")
    return results, time.perf_counter() - started


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1)] if ordered else float("nan")


def summarize(name, outcomes, wall):
    statuses = {}
    for o in outcomes:
        statuses[o.status] = statuses.get(o.status, 0) + 1
    retried = sum(1 for o in outcomes if len(o.attempts) > 1)
    first_try = {}
    for o in outcomes:
        first_try[o.attempts[0]] = first_try.get(o.attempts[0], 0) + 1
    lat = [o.latency * 1000 for o in outcomes]
    total = [o.total * 1000 for o in outcomes]
    return {
        "phase": name, "requests": len(outcomes), "final_status": statuses, "first_attempt_status": first_try, "retried": retried,
        "wall_s": round(wall, 2), "throughput_per_s": round(len(outcomes) / wall, 1),
        "last_attempt_ms": {"p50": round(percentile(lat, 50)), "p95": round(percentile(lat, 95)), "p99": round(percentile(lat, 99)), "max": round(max(lat))},
        "end_to_end_ms": {"p50": round(percentile(total, 50)), "p95": round(percentile(total, 95)), "max": round(max(total))},
    }


# ---------------------------------------------------------------- 서버·시드

class ThreadedServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    request_queue_size = 1024  # 기본(5)이면 동시 접속이 연결 단계에서 거절된다. 운영 서버는 이 값을 크게 둔다


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def seed(advertisers=5, premade=0):
    """관리자·매체·슬롯·광고주(지갑·캠페인·광고그룹 입찰 30·소재)를 만든다. 모든 시각은 실제 현재 시각 기준이다."""
    import io

    from PIL import Image

    from billing import api as billing
    from campaigns import api as campaigns
    from foundation.api import User, create_advertiser
    from masters import api as masters

    admin = User.objects.create_superuser("load_admin", "Tr0ub4dor-horse-staple-9", nickname="관리", class_label="-")
    media = masters.create_media(admin, "부하 시험 매체")
    slot = masters.create_slot(admin, media.media_id, "부하 슬롯", "IMPRESSION", 10, 20, 50, "초기")
    shared = masters.create_slot(admin, media.media_id, "부하 일괄 슬롯", "IMPRESSION", 10, 20, 50, "초기", audience="shared")
    key = masters.issue_media_key(admin, media.media_id).key
    now = datetime.now(UTC)
    wallets = []
    for i in range(advertisers):
        adv = create_advertiser(f"load_adv_{i}", "Tr0ub4dor-horse-staple-9", f"광고주{i}", "1반")
        billing.grant_signup(adv)
        campaign = campaigns.create_campaign(adv, f"캠페인{i}", now - timedelta(days=1), now + timedelta(days=30), 10**9)
        group = campaigns.create_ad_group(adv, campaign.campaign_id, f"그룹{i}", "IMPRESSION", [slot.slot_id], bid_amount=30)
        image = io.BytesIO()
        Image.new("RGB", (32, 32), (20 * i, 80, 200)).save(image, "PNG")
        image.seek(0)
        campaigns.create_creative(adv, group.ad_group_id, f"제목{i}", "https://example.com/landing", image)
        if i == 0:  # 일괄 슬롯에는 광고주 한 명의 광고만 놓는다(입찰 40)
            shared_group = campaigns.create_ad_group(adv, campaign.campaign_id, "일괄 그룹", "IMPRESSION", [shared.slot_id], bid_amount=40)
            image2 = io.BytesIO()
            Image.new("RGB", (32, 32), (200, 80, 20)).save(image2, "PNG")
            image2.seek(0)
            campaigns.create_creative(adv, shared_group.ad_group_id, "일괄 제목", "https://example.com/board", image2)
        wallets.append(adv)
    return {"media_id": media.media_id, "slot_id": slot.slot_id, "shared_slot_id": shared.slot_id, "key": key, "advertisers": wallets}


def make_decisions(ctx, count):
    from records import api as records

    return [str(records.decide(ctx["media_id"], ctx["slot_id"], subject_id=str(uuid.uuid4())).decision_id) for _ in range(count)]


def now_utc():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 단계

class Harness:
    quiescent = False  # 단위 시험이 이미 열린 트랜잭션 안에서 부를 때만 True(`verify_invariants` 참고)

    def __init__(self, port, ctx, count, tmp, log, rest_scale=1.0):
        self.port, self.ctx, self.n, self.tmp, self.log, self.rest_scale = port, ctx, count, tmp, log, rest_scale
        self.key = ctx["key"]
        self.acked_decisions, self.acked_reactions, self.phases, self.checks = set(), {}, [], []

    def rest(self, seconds=3.0):
        time.sleep(seconds * self.rest_scale)  # 요청 제한 버킷이 다시 차도록(150/초). --small 은 요청이 적어 짧게

    def check(self, name, ok, detail=""):
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        self.log(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
        return ok

    def phase(self, name, outcomes, wall):
        summary = summarize(name, outcomes, wall)
        self.phases.append(summary)
        self.log(f"  {name}: {summary['requests']}건 최종 {summary['final_status']} (첫 시도 {summary['first_attempt_status']}, 재시도 {summary['retried']}건) "
                 f"{summary['throughput_per_s']}/s, 마지막 시도 p50/p95/p99/max = {summary['last_attempt_ms']['p50']}/{summary['last_attempt_ms']['p95']}/"
                 f"{summary['last_attempt_ms']['p99']}/{summary['last_attempt_ms']['max']} ms")
        return summary

    def post_decision(self, retry=True, shared=False):
        body = {"slot_id": str(self.ctx["shared_slot_id" if shared else "slot_id"]), "context": {"scene": "load"}}
        if not shared:
            body["subject_id"] = str(uuid.uuid4())  # 일괄 슬롯의 결정에는 사람이 없다
        return call(self.port, "POST", "/api/media/v1/decisions", self.key, body, retry=retry)

    def follow_click(self, click_url, viewer=None):
        """사용자 브라우저처럼 `click_url` 을 연다(인증 없음, 리다이렉트는 따라가지 않는다). 일괄 슬롯은 `{subject_id}` 자리에 사람을 넣는다."""
        path = click_url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path.replace("{subject_id}", viewer or "")
        return call(self.port, "GET", path, None)

    def put_reaction(self, decision_id, rtype="IMPRESSION", reaction_id=None, retry=True, occurred_at=None, subject_id=None):
        """`occurred_at` 을 주면 그대로 쓴다. **같은 reaction_id 의 재전송은 같은 본문**이어야 하므로(다르면 409) 호출하는 쪽이 한 번 만들어 넘긴다."""
        rid = reaction_id or str(uuid.uuid4())
        body = {"type": rtype, "occurred_at": occurred_at or now_utc()}
        if subject_id is not None:
            body["subject_id"] = subject_id
        outcome = call(self.port, "PUT", f"/api/media/v1/decisions/{decision_id}/reactions/{rid}", self.key, body, retry=retry)
        if outcome.acked:
            self.acked_reactions[(str(self.ctx["media_id"]), rid)] = (str(decision_id), rtype)
        return outcome

    def get_reaction(self, decision_id, rid):
        return call(self.port, "GET", f"/api/media/v1/decisions/{decision_id}/reactions/{rid}", self.key)

    def drain(self):
        out = subprocess.run([sys.executable, "manage.py", "process_reactions", "--once"], cwd=BASE_DIR, env=os.environ, capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise RuntimeError(out.stderr[-500:])
        return out.stdout.strip()

    def drain_until(self, settled, what, limit_seconds=60):
        """처리를 돌리고 `settled()` 가 참이 될 때까지 재확인 간격마다 다시 돌린다.

        같은 유형의 반응이 동시에 처리되면 뒤쪽은 먼저 접수된 쪽이 끝나길 **기다린다**(보류, 2-13 후속: 인정되는 쪽은 처리 순서가 아니라 접수 순서가 정한다).
        보류분은 `REACTION_HOLD_RECHECK_SECONDS` 가 지나야 다시 판정되므로 한 번의 `--once` 로는 덜 끝날 수 있다 — 운영의 상시 처리 프로세스가 하는 일이다.
        """
        from django.conf import settings

        deadline = time.perf_counter() + limit_seconds
        while True:
            self.drain()
            if settled():
                return
            if time.perf_counter() > deadline:
                self.check(f"처리가 끝난다: {what}", False, f"{limit_seconds}초 안에 끝나지 않았다")
                return
            time.sleep(settings.REACTION_HOLD_RECHECK_SECONDS + 0.5)

    def settle_events(self, relays):
        """상시 중계가 outbox 를 비우길 기다린 뒤 멈추고, 남은 것은 `relay_events --once` 로 비운다. 중계 프로세스가 죽어 있으면 실패로 남긴다."""
        from events.models import EventOutbox

        deadline = time.perf_counter() + 60
        while time.perf_counter() < deadline and EventOutbox.objects.filter(sent_at__isnull=True).exists():
            time.sleep(0.5)
        left = EventOutbox.objects.filter(sent_at__isnull=True).count()
        self.check("상시 중계 프로세스만으로 outbox 가 비워진다(별도 명령 없이)", left == 0, f"남은 미전송 {left}건")
        self.check("상시 중계 프로세스 둘이 살아 있다", all(p.poll() is None for p in relays), str([p.poll() for p in relays]))
        for proc in relays:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
        out = subprocess.run([sys.executable, "manage.py", "relay_events", "--once"], cwd=BASE_DIR, env=os.environ, capture_output=True, text=True, timeout=300)
        self.check("남은 이벤트를 --once 로 비운다", out.returncode == 0, out.stderr[-200:])

    # ------------------------------------------------------------ H. Step 4-3 (구간 manifest·백필)
    def _manage(self, *args, timeout=300):
        return subprocess.run([sys.executable, "manage.py", *args], cwd=BASE_DIR, env=os.environ, capture_output=True, text=True, timeout=timeout)

    @staticmethod
    def _as_of():
        """내일 00:02:01 UTC — 오늘의 창이 모두 닫힌(창 끝 + 여유 뒤) 시점을 재현한다. 시험이 실제 자정을 기다리지 않게 한다."""
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=2, second=1, microsecond=0)
        return tomorrow.isoformat()

    def hop_lines(self, directory):
        from events import ndjson

        out = {}
        for hop in ("hop_source", "hop_outbox", "hop_mongo"):
            manifest = ndjson.read_manifest(ndjson.manifest_path(directory, hop))
            out[hop] = (directory / manifest["file"]).read_text()
        return out

    def hop_check(self, label):
        """`export_hop_manifests`(오늘의 창을 닫아서) → `verify_hops`: 세 구간·모든 창이 일치해야 한다. 반환: 구간별 줄."""
        directory = self.tmp / "hops"
        exported = self._manage("export_hop_manifests", "--out", str(directory), "--as-of", self._as_of())
        verified = self._manage("verify_hops", "--dir", str(directory), "--out", str(self.tmp / f"hop-report-{label}"))
        clean = exported.returncode == 0 and verified.returncode == 0 and "mismatch" not in verified.stdout and "relay_lag_candidate" not in verified.stdout
        self.check(f"구간별 정합 manifest 가 일치한다 [{label}]: 원본 기대 = outbox = MongoDB(모든 창, 세대 사슬·감사 고정점 확인)", clean,
                   (exported.stderr + verified.stdout)[-300:])
        return self.hop_lines(directory) if exported.returncode == 0 else {}

    def backfill_drill(self, count=60):
        """백필 훈련: 이벤트를 일부러 지워(outbox 와 MongoDB 에서) '이벤트가 없는 원본 행'을 만들고, 목록 → 백필 → 중계 → 점검이 모두 맞물려 원래대로 돌아오는지 본다."""
        import random

        from events import ndjson, store
        from events.models import EventOutbox

        before = self.hop_check("백필 전")
        ids = random.Random(7).sample(list(EventOutbox.objects.values_list("event_id", flat=True)), min(count, EventOutbox.objects.count()))
        EventOutbox.objects.filter(pk__in=ids).delete()
        store.collection().delete_many({"_id": {"$in": ids}})
        self.check("(훈련) 지운 이벤트를 이벤트 검사기가 잡는다", bool(verify_events(relayed=True)))
        gaps_dir, result_dir, clean_dir = self.tmp / "gaps", self.tmp / "backfill", self.tmp / "clean"
        found = self._manage("export_integrity", "--out", str(gaps_dir))
        rows = ndjson.read_manifest(ndjson.manifest_path(gaps_dir, "event_gaps"))["rows"]
        self.check("(훈련) 누락 목록(event_gaps)이 지운 만큼 나온다", found.returncode != 0 and rows == len(ids), f"{rows}/{len(ids)}건")
        dry = self._manage("backfill_events", "--input", str(ndjson.manifest_path(gaps_dir, "event_gaps")), "--out", str(self.tmp / "dry"))
        self.check("백필 --dry-run 은 아무것도 쓰지 않는다", dry.returncode == 0 and EventOutbox.objects.filter(pk__in=ids).count() == 0, dry.stderr[-200:])
        done = self._manage("backfill_events", "--input", str(ndjson.manifest_path(gaps_dir, "event_gaps")), "--out", str(result_dir), "--apply")
        self.check("백필 --apply 가 성공한다", done.returncode == 0, (done.stdout + done.stderr)[-300:])
        relayed = self._manage("relay_events", "--once")
        self.check("백필한 이벤트를 중계가 MongoDB 로 보낸다", relayed.returncode == 0, relayed.stderr[-200:])
        clean = self._manage("export_integrity", "--out", str(clean_dir))
        self.check("백필 뒤 점검(export_integrity)에 누락이 없다", clean.returncode == 0, (clean.stdout + clean.stderr)[-300:])
        problems = verify_events(relayed=True)
        self.check("백필한 이벤트가 원본·봉투·내용 대조와 MongoDB 대조를 특별 처리 없이 통과한다", not problems, "; ".join(problems))
        again = self._manage("backfill_events", "--input", str(ndjson.manifest_path(gaps_dir, "event_gaps")), "--out", str(self.tmp / "again"), "--apply")
        self.check("백필을 다시 돌려도 이벤트가 늘지 않는다", again.returncode == 0 and EventOutbox.objects.filter(pk__in=ids).count() == len(ids), again.stderr[-200:])
        after = self.hop_check("백필 뒤")
        self.check("백필 뒤 구간 manifest 의 요약값이 지우기 전과 같다(같은 창·같은 이벤트·같은 내용)", bool(before) and before == after, "요약값이 달라졌다" if before != after else "")
        from events import api as events_api

        chain = events_api.verify_chain(events_api.manifest_path(self.tmp / "hops", "hop_source"))
        self.check("구간 manifest 세대 사슬이 이어진다(백필 전 → 후)", not chain, "; ".join(chain))

    def verify(self, name, expect_drained=True, events_relayed=False):
        problems = verify_invariants(self.acked_decisions, self.acked_reactions, expect_drained, quiescent=self.quiescent) + verify_events(events_relayed)
        self.check(f"불변식 [{name}]", not problems, "; ".join(problems))
        return not problems

    # ------------------------------------------------------------ A. 동시 결정
    def decisions(self):
        self.log(f"A. {self.n}개 동시 결정(POST /decisions)")
        outcomes, wall = run_concurrent(self.n, lambda i: self.post_decision())
        self.phase("A 동시 결정", outcomes, wall)
        ids = [o.body["decision_id"] for o in outcomes if o.status == 201]
        self.acked_decisions |= set(ids)
        self.check("모든 결정이 201 로 수신 확인됐다", len(ids) == self.n, f"{len(ids)}/{self.n}")
        self.check("결정 ID 가 모두 다르다", len(set(ids)) == len(ids))
        self.verify("결정 직후", expect_drained=True)
        self.decision_ids = ids

    # ------------------------------------------------------------ B. 동시 반응
    def reactions(self):
        self.log(f"B. {self.n}개 동시 반응(PUT, 서로 다른 결정·수신 직후 처리 켜짐)")
        outcomes, wall = run_concurrent(self.n, lambda i: self.put_reaction(self.decision_ids[i]))
        self.phase("B 동시 반응", outcomes, wall)
        self.check("모든 반응이 201 로 수신 확인됐다", all(o.status == 201 for o in outcomes), str(sorted({o.status for o in outcomes})))
        self.log("   남은 것 처리(process_reactions --once): " + self.drain())
        rids = [o.body["reaction_id"] for o in outcomes]  # 인덱스 순서(완료 순서가 아니다)
        reads, wall = run_concurrent(self.n, lambda i: self.get_reaction(self.decision_ids[i], rids[i]))
        self.phase("B' 동시 조회", reads, wall)
        states = {}
        for o in reads:
            states[o.body["status"]] = states.get(o.body["status"], 0) + 1
        self.check("모든 반응이 인정됐고 과금됐다", states == {"ACCEPTED": self.n}, str(states))
        self.verify("반응 직후")

    # ------------------------------------------------------------ C. 같은 결정·유형을 서로 다른 반응 ID 로 동시 보고
    def duplicate_types(self):
        self.log(f"C. 같은 결정에 같은 유형을 서로 다른 reaction_id {self.n}개로 동시 보고")
        (decision,) = make_decisions(self.ctx, 1)
        self.acked_decisions.add(decision)
        outcomes, wall = run_concurrent(self.n, lambda i: self.put_reaction(decision, "IMPRESSION"))
        self.phase("C 같은 유형 동시", outcomes, wall)
        from records.models import Reaction

        self.drain_until(lambda: not Reaction.objects.filter(decision_id=decision, status="RECEIVED").exists(), "같은 유형 동시 노출")

        states = {}
        for r in Reaction.objects.filter(decision_id=decision):
            states[r.status] = states.get(r.status, 0) + 1
        self.check("정확히 하나만 인정, 나머지는 duplicate_type", states == {"ACCEPTED": 1, "REJECTED": self.n - 1}, str(states))
        three = max(3, self.n // 3 * 3)
        (decision2,) = make_decisions(self.ctx, 1)
        self.acked_decisions.add(decision2)
        kinds = ["IMPRESSION", "CLICK", "CONVERSION"]
        outcomes, wall = run_concurrent(three, lambda i: self.put_reaction(decision2, kinds[i % 3]))
        self.phase("C' 세 유형 동시", outcomes, wall)
        self.drain_until(lambda: set(Reaction.objects.filter(decision_id=decision2, status="RECEIVED").values_list("type", flat=True)) <= {"CONVERSION"}, "세 유형 동시")
        by_type = {}
        for r in Reaction.objects.filter(decision_id=decision2):
            by_type.setdefault(r.type, []).append(r.status)
        # 노출만 인정된다(나머지 노출은 중복 거부): 매체가 보고한 클릭은 거부(click_not_reported), 클릭 없는 전환은 클릭을 기다리며 보류(RECEIVED)
        ok = (
            by_type.get("IMPRESSION", []).count("ACCEPTED") == 1 and set(by_type.get("IMPRESSION", [])) <= {"ACCEPTED", "REJECTED"}
            and set(by_type.get("CLICK", [])) == {"REJECTED"} and set(by_type.get("CONVERSION", [])) == {"RECEIVED"}
        )
        self.check("노출 하나만 인정·매체 클릭은 거부·클릭 없는 전환은 보류", ok, str({t: sorted(set(v)) for t, v in by_type.items()}))
        self.verify("유형 중복")

    # ------------------------------------------------------------ D. 같은 reaction_id 재전송 폭주
    def resend_storm(self):
        self.log(f"D. 같은 reaction_id 를 {self.n}개 동시에 재전송")
        (decision,) = make_decisions(self.ctx, 1)
        self.acked_decisions.add(decision)
        rid, occurred_at = str(uuid.uuid4()), now_utc()  # 논리 반응 하나: ID 와 본문(시각)을 스레드 시작 전에 한 번만 만든다
        outcomes, wall = run_concurrent(self.n, lambda i: self.put_reaction(decision, "CLICK", reaction_id=rid, occurred_at=occurred_at))
        self.phase("D 재전송 폭주", outcomes, wall)
        counts = {s: sum(1 for o in outcomes if o.status == s) for s in (200, 201)}
        self.check("201 하나, 나머지는 200", counts == {200: self.n - 1, 201: 1}, str(counts))
        from records.models import Reaction

        self.check("행은 하나", Reaction.objects.filter(reaction_id=rid).count() == 1)
        self.verify("재전송 폭주")

    # ------------------------------------------------------------ H. 클릭 경유 전체 퍼널(개인 슬롯)
    def click_funnel(self):
        self.log(f"H. 개인 슬롯 전체 퍼널 {self.n}건 동시: 결정 → 노출 → 클릭(click_url, 인증 없음) → 전환")
        from records.models import Reaction

        def one(i):
            decision = self.post_decision()
            did = decision.body["decision_id"]
            self.acked_decisions.add(did)
            impression = self.put_reaction(did, "IMPRESSION")
            click = self.follow_click(decision.body["ad"]["click_url"])
            conversion = self.put_reaction(did, "CONVERSION")
            return did, impression, click, conversion

        results, wall = run_concurrent(self.n, one)
        self.phase("H 클릭 경유 퍼널", [r[2] for r in results], wall)
        self.check("클릭은 모두 302 이고 이동 주소는 결정에 저장된 값이다",
                   all(r[2].status == 302 and r[2].headers.get("location") == "https://example.com/landing" for r in results), str(sorted({r[2].status for r in results})))
        self.check("클릭 응답은 no-store·no-referrer 이고 쿠키가 없다",
                   all(r[2].headers.get("cache-control") == "no-store" and r[2].headers.get("referrer-policy") == "no-referrer" and "set-cookie" not in r[2].headers for r in results))
        self.drain()
        ids = [r[0] for r in results]
        by_decision = {}
        for row in Reaction.objects.filter(decision_id__in=ids):
            by_decision.setdefault(str(row.decision_id), {})[row.type] = row.status
        self.check("결정마다 노출·클릭·전환이 모두 인정됐다", all(v == {"IMPRESSION": "ACCEPTED", "CLICK": "ACCEPTED", "CONVERSION": "ACCEPTED"} for v in by_decision.values()) and len(by_decision) == self.n,
                   str({tuple(sorted(v.values())) for v in by_decision.values()}))
        self.check("서버가 관측한 클릭이 결정마다 정확히 하나", Reaction.objects.filter(decision_id__in=ids, source="server").count() == self.n)
        self.verify("클릭 경유 퍼널")

    # ------------------------------------------------------------ J. 일괄 슬롯: 사람별 퍼널, 노출 없는 임의 s 의 클릭
    def shared_slot_funnel(self):
        viewers = [str(uuid.uuid4()) for _ in range(self.n)]
        forged = [str(uuid.uuid4()) for _ in range(5)]
        self.log(f"J. 일괄 슬롯: 결정 1개를 시청자 {len(viewers)}명이 각자 보고(노출·클릭·전환), 노출 없는 임의 s 클릭 {len(forged)}건")
        from records.models import Reaction

        decision = self.post_decision(shared=True)
        did = decision.body["decision_id"]
        self.check("일괄 슬롯 결정은 사람 없이 201 이고 audience=shared", decision.status == 201 and decision.body["audience"] == "shared")
        self.acked_decisions.add(did)
        template = decision.body["ad"]["click_url"]

        def one(i):
            person = viewers[i]
            return (
                self.put_reaction(did, "IMPRESSION", subject_id=person), self.follow_click(template, person), self.put_reaction(did, "CONVERSION", subject_id=person),
            )

        results, wall = run_concurrent(len(viewers), one)
        self.phase("J 일괄 슬롯 시청자", [r[1] for r in results], wall)
        fake = [self.follow_click(template, person) for person in forged]
        self.check("임의 s 의 클릭도 사용자에게는 302 (이동은 판정과 무관)", all(c.status == 302 for c in fake))
        self.drain()
        accepted = {}
        for row in Reaction.objects.filter(decision_id=did, status="ACCEPTED"):
            accepted.setdefault(row.person_id, set()).add(row.type)
        self.check("시청자마다 노출·클릭·전환이 인정됐다", set(accepted) == set(viewers) and all(t == {"IMPRESSION", "CLICK", "CONVERSION"} for t in accepted.values()),
                   f"{len(accepted)}명")
        pending = list(Reaction.objects.filter(decision_id=did, subject_id__in=forged))
        self.check("노출 없는 임의 s 의 클릭은 인정되지 않고 보류로 남는다", len(pending) == len(forged) and all(r.status == "RECEIVED" for r in pending),
                   str({r.status for r in pending}))
        self.verify("일괄 슬롯")

    # ------------------------------------------------------------ I. 보류 해소 지연: 처리 프로세스가 돌아야 풀린다
    def hold_resolution(self, count=10):
        count = min(count, self.n)
        self.log(f"I. 클릭이 노출보다 먼저 온 {count}건: 처리 프로세스가 없으면 보류로 남고, 뜨면 재확인 간격 안에 인정된다")
        from django.conf import settings

        from records.models import Reaction

        def one(i):
            decision = self.post_decision()
            did = decision.body["decision_id"]
            self.acked_decisions.add(did)
            click = self.follow_click(decision.body["ad"]["click_url"])  # 노출보다 먼저
            impression = self.put_reaction(did, "IMPRESSION")
            return did, click, impression

        results, _ = run_concurrent(count, one)
        ids = [r[0] for r in results]
        time.sleep(1.0)
        held = Reaction.objects.filter(decision_id__in=ids, source="server", status="RECEIVED").count()
        self.check("처리 프로세스가 없으면 클릭은 보류로 남는다(노출이 인정돼도 즉시 깨우지 않는다)", held == count, f"{held}/{count}")
        log_file = open(self.tmp / "hold.log", "w")
        started = time.perf_counter()
        proc = subprocess.Popen([sys.executable, "manage.py", "process_reactions", "--interval", "0.5"], cwd=BASE_DIR, env=os.environ, stdout=log_file, stderr=log_file)
        limit = settings.REACTION_HOLD_RECHECK_SECONDS + 10
        try:
            while time.perf_counter() - started < limit and Reaction.objects.filter(decision_id__in=ids, source="server", status="ACCEPTED").count() < count:
                time.sleep(0.25)
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=30)
            log_file.close()
        elapsed = round(time.perf_counter() - started, 1)
        done = Reaction.objects.filter(decision_id__in=ids, source="server", status="ACCEPTED").count()
        self.hold_seconds = elapsed
        self.check(f"처리 프로세스가 뜨면 보류가 재확인 간격({settings.REACTION_HOLD_RECHECK_SECONDS}초) 안팎에 풀린다", done == count, f"{done}/{count}, {elapsed}초")
        self.verify("보류 해소")

    # ------------------------------------------------------------ E. 지속 유입 중 SIGTERM·동시 처리 프로세스·재기동
    def sigterm_under_inflow(self, inflow_seconds=6.0):
        from django.conf import settings

        from records.models import Reaction

        self.log(f"E. 지속 유입 중 처리 프로세스 2개 동시 실행 → SIGTERM → 재기동 ({inflow_seconds:.0f}초 유입)")
        pool = make_decisions(self.ctx, max(200, self.n * 2))
        self.acked_decisions |= set(pool)
        settings.REACTION_PROCESS_ON_RECEIPT = False  # 처리를 별도 프로세스에 맡겨 대기열이 쌓이게 한다
        stop, cursor, lock = threading.Event(), [0], threading.Lock()

        def inflow(_i):
            mine = []
            while not stop.is_set():
                with lock:
                    first_use = cursor[0] < len(pool)
                    decision = pool[cursor[0]] if first_use else random.choice(pool)
                    cursor[0] += 1
                # 처음 쓰는 결정에는 과금 대상인 노출, 그 뒤에는 아무 결정에 아무 유형(중복 거부·유형별 인정이 섞인다)
                mine.append(self.put_reaction(decision, "IMPRESSION" if first_use else random.choice(["IMPRESSION", "CLICK", "CONVERSION"])))
            return mine

        pending = []
        workers = threading.Thread(target=lambda: pending.append(run_concurrent(max(4, self.n // 10), inflow)))
        workers.start()
        time.sleep(inflow_seconds / 3)  # 처리 프로세스 없이 대기열이 쌓이게 둔다
        logs, procs = [], []
        for name in ("p1", "p2"):
            handle = open(self.tmp / f"{name}.log", "w")
            logs.append(handle)
            procs.append(subprocess.Popen([sys.executable, "manage.py", "process_reactions", "--batch", "10", "--interval", "0.2"], cwd=BASE_DIR, env=os.environ, stdout=handle, stderr=handle))
        ready = time.perf_counter()
        while time.perf_counter() - ready < 60 and not all("started" in (self.tmp / f"{n}.log").read_text() for n in ("p1", "p2")):
            time.sleep(0.1)  # 두 프로세스 모두 신호 처리기를 설치하고 시작 로그를 남길 때까지 기다린다
        time.sleep(inflow_seconds / 3)  # 그 뒤 대기열을 실제로 처리하는 동안
        exits = {}
        backlog_at_term = Reaction.objects.filter(status="RECEIVED").count()
        t0 = time.perf_counter()
        procs[0].send_signal(signal.SIGTERM)
        codes = {"p1": procs[0].wait(timeout=30)}
        exits["p1_exit_s"] = round(time.perf_counter() - t0, 2)
        time.sleep(inflow_seconds / 3)
        stop.set()
        workers.join(timeout=120)
        t0 = time.perf_counter()
        procs[1].send_signal(signal.SIGTERM)
        codes["p2"] = procs[1].wait(timeout=30)
        exits["p2_exit_s"] = round(time.perf_counter() - t0, 2)
        [h.close() for h in logs]
        settings.REACTION_PROCESS_ON_RECEIPT = True
        results, wall = pending[0]
        flat = [o for part in results for o in part]
        self.phase("E 지속 유입", flat, wall)
        left = Reaction.objects.filter(status="RECEIVED").count()
        self.log(f"   SIGTERM 종료 시간 {exits}, 종료 시점 대기열 {backlog_at_term}건, 두 프로세스 종료 후 대기열 {left}건")
        self.check("SIGTERM 시점에 처리할 대기열이 있었다(시험이 공회전이 아니다)", backlog_at_term > 0, f"{backlog_at_term}건")
        self.check("두 프로세스 모두 정상 종료 코드 0 (신호 처리기로 멈췄다. 기본 동작으로 죽지 않았다)", set(codes.values()) == {0}, str(codes))
        self.check("SIGTERM 은 몇 초 안에 끝난다(큐를 비울 때까지 끌지 않는다)", max(exits.values()) < 10, str(exits))
        self.check("종료 때 남은 반응은 RECEIVED 로 있다(유실·임의 거부 없음)", left > 0 and Reaction.objects.count() >= len(flat), f"남은 {left}건")
        self.verify("SIGTERM 직후(재기동 전)", expect_drained=False)
        started = time.perf_counter()
        summary = self.drain()
        self.log(f"   재기동(process_reactions --once) {time.perf_counter() - started:.1f}초: " + summary)
        left_after = list(Reaction.objects.filter(status="RECEIVED").values_list("type", flat=True))
        self.check("재기동 뒤 남김없이 처리(앞 단계를 기다리는 클릭·전환 보류만 남는다)", set(left_after) <= {"CLICK", "CONVERSION"}, str({t: left_after.count(t) for t in set(left_after)}))
        self.verify("재기동 뒤")
        self.exits = exits

    # ------------------------------------------------------------ F. 요청 제한
    def rate_limit_burst(self):
        from django.conf import settings

        burst = settings.MEDIA_RATE_LIMITS["decisions"][1] + 100
        self.log(f"F. 요청 제한: {burst}개 동시 결정(재시도 없음) — 버스트 {settings.MEDIA_RATE_LIMITS['decisions'][1]} 초과분은 429 + Retry-After")
        self.rest(4)
        outcomes, wall = run_concurrent(burst, lambda i: self.post_decision(retry=False))
        self.phase("F 버스트 초과", outcomes, wall)
        statuses = {o.status for o in outcomes}
        limited = [o for o in outcomes if o.status == 429]
        self.acked_decisions |= {o.body["decision_id"] for o in outcomes if o.status == 201}
        self.check("201 과 429 외 상태가 없다", statuses <= {201, 429}, str(statuses))
        self.check("429 에는 모두 정수 Retry-After 가 있다", all(o.headers.get("retry-after", "").isdigit() for o in limited), f"{len(limited)}건")
        self.verify("요청 제한")

    # ------------------------------------------------------------ G. 요청당 비용
    def per_request_cost(self, samples=200):
        """한 스레드로 결정 요청의 질의 수와 `slot_name` 조회가 더하는 시간을 잰다(HTTP 를 거치지 않는 서버 안쪽 비용)."""
        from unittest import mock

        from django.db import connection
        from django.test import Client
        from django.test.utils import CaptureQueriesContext, override_settings

        from serving_api.throttle import buckets

        body = json.dumps({"slot_id": str(self.ctx["slot_id"]), "subject_id": str(uuid.uuid4())})
        client = Client()

        def post():
            return client.post("/api/media/v1/decisions", data=body, content_type="application/json", HTTP_X_MEDIA_KEY=self.key)

        with override_settings(ALLOWED_HOSTS=["*"], MEDIA_RATE_LIMITS={"decisions": (10**6, 10**6), "reactions": (10**6, 10**6), "reads": (10**6, 10**6)}):
            buckets.reset()
            with CaptureQueriesContext(connection) as queries:
                assert post().status_code == 201
            kinds = {}
            for q in queries.captured_queries:
                kind = q["sql"].split(None, 1)[0].upper()
                kinds[kind] = kinds.get(kind, 0) + 1
            samples_ms = {}
            for label, patch in (("with_slot_name", None), ("without_slot_name", lambda ids: {})):
                times = []
                for _ in range(samples):
                    t0 = time.perf_counter()
                    if patch is None:
                        response = post()
                    else:
                        with mock.patch("serving_api.views.masters.slot_names", patch):
                            response = post()
                    times.append((time.perf_counter() - t0) * 1000)
                    assert response.status_code == 201
                samples_ms[label] = round(statistics.median(times), 2)
            buckets.reset()
        for body_id in Decision_ids_since(samples * 2 + 1):
            self.acked_decisions.add(body_id)
        cost = round(samples_ms["with_slot_name"] - samples_ms["without_slot_name"], 2)
        self.cost = {"queries_per_decision_post": sum(kinds.values()), "by_kind": kinds, "median_ms": samples_ms, "slot_name_cost_ms": cost}
        self.log(f"G. 결정 요청 1건: 질의 {sum(kinds.values())}개 {kinds}, 서버 안쪽 중앙값 {samples_ms} ms, slot_name 조회 비용 ≈ {cost} ms")


def Decision_ids_since(count):
    from records.models import Decision

    return [str(i) for i in Decision.objects.order_by("-decided_at").values_list("decision_id", flat=True)[:count]]


# ---------------------------------------------------------------- 실행

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--concurrency", type=int, default=150, help="동시 요청 수(기본 150)")
    parser.add_argument("--small", action="store_true", help="20 동시, 짧은 유입(몇 초)")
    parser.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    parser.add_argument("--keep", action="store_true", help="임시 폴더와 데이터베이스를 지우지 않는다")
    args = parser.parse_args(argv)
    count = 20 if args.small else args.concurrency

    sys.path.insert(0, str(BASE_DIR))
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    os.chdir(BASE_DIR)
    import mysql_admin

    # 자원은 만드는 즉시 기록하고, 어느 단계에서 실패해도(준비·시험·결과 저장) 만든 것만 바깥 finally 가 정리한다.
    res = {"tmp": None, "db": None, "server": None, "serving": False, "mongo_db": None, "relays": []}
    try:
        res["tmp"] = tmp = Path(tempfile.mkdtemp(prefix="ads-load-"))
        res["db"] = db_name = mysql_admin.create_database("ads_load")  # 접속 값이 없거나 연결이 안 되면 여기서 이유를 말하고 멈춘다
        res["mongo_db"] = f"ads_events_load_{uuid.uuid4().hex}"  # 이 실행만 쓰는 무작위 이름. 끝나면 이 이름만 지운다
        return run(args, count, tmp, db_name, res)
    finally:
        cleanup(res, keep=args.keep)


def cleanup(res, keep):
    if keep:
        print(f"남겨 둠: 폴더 {res['tmp']}, 데이터베이스 {res['db']}")
        return
    import mysql_admin

    def stop_server():
        if res["serving"]:  # serve_forever 가 돈 적이 없으면 shutdown() 은 영원히 기다린다
            res["server"].shutdown()
        if res["server"]:
            res["server"].server_close()

    def close_connections():
        if "django.db" in sys.modules:
            sys.modules["django.db"].connections.close_all()

    def stop_relays():
        for proc in res["relays"]:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def drop_mongo():
        name = res["mongo_db"]
        if name and name.startswith("ads_events_load_") and "events" in sys.modules:
            from events import mongo

            mongo.client().drop_database(name)
            mongo.close()

    steps = [
        ("중계 프로세스 종료", stop_relays),
        ("서버 종료", stop_server),
        ("연결 닫기", close_connections),
        ("MongoDB 데이터베이스 삭제", drop_mongo),
        ("데이터베이스 삭제", lambda: res["db"] and mysql_admin.drop_database(res["db"])),
        ("임시 폴더 삭제", lambda: res["tmp"] and shutil.rmtree(res["tmp"], ignore_errors=True)),
    ]
    for label, step in steps:  # 한 단계가 실패해도 나머지는 계속한다
        try:
            step()
        except Exception as exc:  # noqa: BLE001 — 정리 실패는 알리고 원래 오류를 가리지 않는다
            print(f"정리 실패({label}): {exc!r}", file=sys.stderr)


def run(args, count, tmp, db_name, res):
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings.dev", DB_NAME=db_name, MONGO_DB=res["mongo_db"], MEDIA_ROOT=str(tmp / "media"))
    os.environ.pop("DJANGO_DEBUG", None)

    import django

    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application

    from events import store

    log = print
    log(f"임시 폴더 {tmp}, 데이터베이스 {db_name} (MySQL 8.4), 동시 {count}")
    call_command("migrate", verbosity=0)
    store.ensure()  # 운영과 같은 봉투 검증이 걸린 이 실행 전용 컬렉션
    ctx = seed()
    for i in range(2):  # 상시 중계 프로세스 둘이 처음부터 끝까지 돈다(서로 다른 행을 가져가는지도 함께 본다)
        log_file = open(tmp / f"relay{i}.log", "w")
        res["relays"].append(subprocess.Popen([sys.executable, "manage.py", "relay_events", "--interval", "0.3", "--batch", "50"], cwd=BASE_DIR, env=os.environ, stdout=log_file, stderr=log_file))
    server = ThreadedServer(("127.0.0.1", 0), QuietHandler)
    res["server"] = server
    server.set_app(get_wsgi_application())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    res["serving"] = True
    harness = Harness(server.server_address[1], ctx, count, tmp, log, rest_scale=0.1 if args.small else 1.0)
    from django.conf import settings

    lag = LagSampler()
    lag.start()  # 이벤트가 생성 시각으로부터 얼마 뒤에 보이는지 처음부터 끝까지 잰다
    try:
        harness.decisions()
        harness.rest()
        harness.reactions()
        harness.rest()
        harness.duplicate_types()
        harness.rest()
        harness.resend_storm()
        harness.rest()
        harness.click_funnel()
        harness.rest()
        harness.shared_slot_funnel()
        harness.rest()
        harness.hold_resolution()
        harness.rest()
        harness.sigterm_under_inflow(inflow_seconds=3.0 if args.small else 6.0)
        harness.rest(4)
        harness.rate_limit_burst()
        harness.drain()
        harness.per_request_cost(samples=50 if args.small else 200)
        harness.drain()
        harness.settle_events(res["relays"])
        harness.verify("최종", events_relayed=True)
        lag.stop()
        harness.event_lag = lag.report(settings.EVENTS_HOP_GRACE_SECONDS)
        r = harness.event_lag
        harness.check(f"이벤트가 생성 시각 뒤 창 닫힘 여유({settings.EVENTS_HOP_GRACE_SECONDS}초) 안에 모두 보인다(설계 H11 A안의 근거)", r["late"] == 0 and r["unobserved"] == 0,
                      f"이벤트 {r['events']}건, 관찰된 최대 지연 {r['max_lag_s']}초, 여유 초과 {r['late']}건, 관찰 못 한 것 {r['unobserved']}건")
        harness.backfill_drill()
    finally:
        lag.stop()
        ok = all(c["ok"] for c in harness.checks)
        from billing.models import LedgerEntry
        from records.models import Decision, Reaction

        totals = {"decisions": Decision.objects.count(), "reactions": Reaction.objects.count(), "charges": LedgerEntry.objects.filter(entry_type="CHARGE").count()}
        log(f"\n저장된 행: {totals}")
        log("결과: " + ("모든 불변식 충족" if ok else "실패 항목 있음 — " + ", ".join(c["check"] for c in harness.checks if not c["ok"])))
        if args.json:
            Path(args.json).write_text(json.dumps({"concurrency": count, "ok": ok, "phases": harness.phases, "checks": harness.checks, "cost": getattr(harness, "cost", None), "sigterm": getattr(harness, "exits", None), "hold_resolution_s": getattr(harness, "hold_seconds", None), "event_lag": getattr(harness, "event_lag", None), "totals": totals}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
