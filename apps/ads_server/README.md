# ads_server

Django 광고 서버. 설계·계획·계약은 [docs/ads-server/](../../docs/ads-server/ads-server-design.md)에 있다.

## 실행

```bash
mamba activate claude
cd apps/ads_server
pip install -r requirements.txt
cp .env.example .env        # 값을 채운다. .env 는 커밋하지 않는다
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

- `.env`는 python-dotenv가 읽고, **실제 환경변수가 `.env`보다 우선**한다.
- 설정은 `config/settings/{dev,prod,test}.py`. `manage.py`는 기본 dev, `manage.py test`는 항상 test, `wsgi/asgi`는 기본 prod.
- prod는 `SECRET_KEY`(50자 이상)·`ALLOWED_HOSTS`·`DATABASE_PATH`가 없으면 기동하지 않는다.
- 관리자 계정은 가입 화면이 없다: `python manage.py createsuperuser`.
- dev 에서는 `DEBUG`가 기본 꺼져 있어 `runserver`가 정적 파일(CSS)을 서빙하지 않는다. 화면을 볼 때는 `DJANGO_DEBUG=1`로 실행한다.

## 테스트와 점검

```bash
python manage.py test                 # 전체 (경계 검사·보안 회귀 포함)
python manage.py test --tag security  # 보안 회귀 묶음만
./scripts/check.sh                    # 일괄 점검: check --deploy, 마이그레이션, 테스트, pip-audit, bandit
OFFLINE_OK=1 ./scripts/check.sh       # 네트워크가 없어 pip-audit 을 못 돌릴 때 건너뛰고 표시
```

`check.sh`는 하나라도 실패하면 비정상 종료한다. `pip-audit`이 네트워크 문제로 못 돌 때와 **실제 취약점이 발견됐을 때**를 구분해 알려준다.

## `check --deploy`

0-4 이후 prod 설정의 경고는 **0**이다(`python -m django check --deploy --fail-level WARNING`, 테스트로 강제).
`security.W021`(HSTS 프리로드)만 **의도적으로 끈다**: 내부 서비스이고 프리로드 등록은 되돌리기 어렵다(`config/settings/prod.py`에 사유).

## 알려진 사항

- 관리자 화면(Django admin)에서 사용자 관리와 감사 로그 열람이 가능하다. 사용자 변경·비밀번호 초기화는 감사 로그에 남고, 감사 로그는 읽기 전용이다.
- 아키텍처 경계(층·`api` 만 import)는 `tests/boundaries/`가 강제한다. 모듈을 추가하면 `test_layers.py`의 `LAYERS`에 등록한다.
- 정적 파일(CSS)은 DEBUG 에서만 `runserver` 가 서빙한다. 운영에서는 웹서버(인프라)가 `STATIC_ROOT` 를 서빙한다.
