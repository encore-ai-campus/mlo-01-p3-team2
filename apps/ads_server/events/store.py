"""`ad_events` 컬렉션의 생성·색인·상태 확인 (계획 DB-2). 이벤트는 아직 쓰지 않는다(Step 4).

컬렉션과 이벤트 스키마가 C2 계약 면이다(설계 §6.3). 아래 봉투 검증과 색인은 DRD §5.6 의 공통 봉투 제안에서 왔고 Step 4 에서 스키마와 함께 확정한다.
"""
import datetime
import uuid
from dataclasses import dataclass

import pymongo
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions
from pymongo.errors import PyMongoError

from . import mongo

COLLECTION = "ad_events"
PROBE_COLLECTION = "ad_events_probe"  # 쓰기 권한 확인 전용. 계약 컬렉션에 확인용 문서를 섞지 않는다
MIN_SERVER_MAJOR = 8

# 색인 이름 → 키. `_id`(= event_id, 유일)는 MongoDB 가 항상 만든다.
INDEXES = {
    "event_name_produced_at": [("event_name", pymongo.ASCENDING), ("produced_at", pymongo.ASCENDING)],  # 이벤트 종류별 시각 순 증분 읽기
    "decision_produced_at": [("payload.decision_id", pymongo.ASCENDING), ("produced_at", pymongo.ASCENDING)],  # 결정 하나의 이벤트 모아 보기(메시지 키)
}

# 공통 봉투(DRD §5.6)가 빠진 문서가 들어오지 못하게 한다. 내용(payload)의 필드는 Step 4 에서 확정한다.
VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["_id", "event_name", "schema_version", "produced_at", "payload"],
    "properties": {
        "_id": {"bsonType": "binData"},
        "event_name": {"bsonType": "string"},
        "schema_version": {"bsonType": ["int", "long"]},
        "produced_at": {"bsonType": "date"},
        "payload": {"bsonType": "object"},
    },
}}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def collection(name=COLLECTION):
    """계약 컬렉션 핸들. UUID 는 표준 표현, 시각은 UTC 시각 인식(tz_aware)으로 읽는다 — 중계의 중복 비교가 같은 형식끼리 이뤄지게."""
    options = CodecOptions(uuid_representation=UuidRepresentation.STANDARD, tz_aware=True, tzinfo=datetime.timezone.utc)
    return mongo.database().get_collection(name, codec_options=options)


_collection = collection


def ensure():
    """컬렉션(봉투 검증 포함)과 색인을 만든다. 여러 번 불러도 같다. 이미 다른 키로 같은 이름의 색인이 있으면 지우지 않고 오류로 멈춘다. 한 일의 목록을 돌려준다."""
    db = mongo.database()
    done = []
    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION, validator=VALIDATOR, validationAction="error", validationLevel="strict")
        done.append(f"컬렉션 {COLLECTION} 생성")
    elif _validator() != VALIDATOR:
        db.command("collMod", COLLECTION, validator=VALIDATOR, validationAction="error", validationLevel="strict")
        done.append(f"컬렉션 {COLLECTION} 봉투 검증 갱신")
    existing = {name: info for name, info in _collection().index_information().items()}
    for name, keys in INDEXES.items():
        if name not in existing:
            _collection().create_index(keys, name=name)
            done.append(f"색인 {name} 생성")
        elif existing[name]["key"] != keys:
            raise RuntimeError(f"색인 {name} 이(가) 다른 키로 이미 있습니다: {existing[name]['key']} (자동으로 지우지 않습니다)")
    return done


def _validator():
    info = mongo.database().list_collections(filter={"name": COLLECTION}).next()
    return info.get("options", {}).get("validator")


def check():
    """연결·서버 버전·(설정했다면) 레플리카셋·쓰기 권한·컬렉션·색인을 확인해 결과 목록을 돌려준다. 연결이 안 되어도 예외로 끝나지 않는다."""
    try:
        cfg = mongo.config()
    except mongo.NotConfigured as exc:
        return [Check("설정", False, str(exc))]
    results = []
    try:
        hello = mongo.client().admin.command("hello")
        version = mongo.client().server_info()["version"]
    except PyMongoError as exc:
        return [Check("연결", False, f"{type(exc).__name__}: {str(exc)[:200]}")]
    results.append(Check("연결", True, f"서버 {version}"))
    if int(version.split(".")[0]) < MIN_SERVER_MAJOR:
        results.append(Check("서버 버전", False, f"{MIN_SERVER_MAJOR}.x 이상이 필요합니다(지금 {version})"))
    if cfg["REPLICA_SET"]:
        results.append(Check("레플리카셋", hello.get("setName") == cfg["REPLICA_SET"], f"설정 {cfg['REPLICA_SET']}, 서버 {hello.get('setName')}, 쓰기 가능 구성원 {'있음' if hello.get('isWritablePrimary') else '없음'}"))
    else:
        results.append(Check("접속 방식", True, "단일 서버(레플리카셋 이름 없음)" if not hello.get("setName") else f"서버는 레플리카셋 {hello['setName']} 의 구성원이다 — MONGO_REPLICA_SET 을 설정해야 failover 를 따라간다"))
    try:
        probe = _collection(PROBE_COLLECTION)
        probe_id = uuid.uuid4()
        probe.insert_one({"_id": probe_id})
        probe.delete_one({"_id": probe_id})
        results.append(Check("쓰기 권한", True, f"{PROBE_COLLECTION} 에 쓰기·삭제 확인(과반 확인)"))
    except PyMongoError as exc:
        results.append(Check("쓰기 권한", False, f"{type(exc).__name__}: {str(exc)[:200]}"))
    try:
        db = mongo.database()
        if COLLECTION not in db.list_collection_names():
            results.append(Check("컬렉션", False, f"{COLLECTION} 이(가) 없습니다 — manage.py ensure_event_store"))
            return results
        results.append(Check("봉투 검증", _validator() == VALIDATOR, "일치" if _validator() == VALIDATOR else "다릅니다 — manage.py ensure_event_store"))
        existing = _collection().index_information()
        for name, keys in INDEXES.items():
            ok = name in existing and existing[name]["key"] == keys
            results.append(Check(f"색인 {name}", ok, "일치" if ok else "없거나 키가 다릅니다 — manage.py ensure_event_store"))
    except PyMongoError as exc:
        results.append(Check("컬렉션", False, f"{type(exc).__name__}: {str(exc)[:200]}"))
    return results
