"""MongoDB 연결 (계획 DB-2). 연결은 처음 쓸 때 만들고(기동 때 연결하지 않는다), 프로세스당 하나를 공유한다(`MongoClient` 는 스레드 안전)."""
import threading

import pymongo
from django.conf import settings

TIMEOUT_MS = 3000  # 서버 선택·연결 대기. 짧게 둬서 저장소가 죽어 있어도 확인 명령이 길게 매달리지 않는다
_lock = threading.Lock()
_client = None


class NotConfigured(Exception):
    pass


def error_text(error):
    """MongoDB(또는 그 설정) 오류를 알리는 한 조각 `<오류 종류>: <메시지 앞 200자>`. 명령의 오류 문구와 상태 확인 결과가 같이 쓴다."""
    return f"{type(error).__name__}: {str(error)[:200]}"


def config():
    """`settings.EVENT_STORE`. 없으면(설정 안 됨) 무엇이 없는지 말하고 멈춘다."""
    cfg = getattr(settings, "EVENT_STORE", None)
    if not cfg or not cfg["HOSTS"]:
        raise NotConfigured("이벤트 저장소 설정이 없습니다(환경변수 MONGO_HOSTS).")
    return cfg


def client_options(cfg):
    options = {
        "host": cfg["HOSTS"],
        "uuidRepresentation": "standard",  # `_id = event_id` 를 UUID(이진 4)로 저장한다(팀 DRD 6.3)
        "w": "majority",  # 레플리카셋에서 과반에 반영된 뒤 성공으로 본다(failover 로 확인된 쓰기가 사라지지 않게)
        "retryWrites": True,
        "serverSelectionTimeoutMS": TIMEOUT_MS,
        "connectTimeoutMS": TIMEOUT_MS,
        "socketTimeoutMS": 10_000,
        "appname": "ads-server",
    }
    if cfg["REPLICA_SET"]:
        options["replicaSet"] = cfg["REPLICA_SET"]
    if cfg["USER"]:
        options.update(username=cfg["USER"], password=cfg["PASSWORD"], authSource=cfg["AUTH_SOURCE"])
    return options


def client():
    global _client
    with _lock:
        if _client is None:
            _client = pymongo.MongoClient(**client_options(config()))
        return _client


def database():
    return client()[config()["NAME"]]


def close():
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
