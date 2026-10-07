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

## 테스트

```bash
python manage.py test                 # 전체
python manage.py test --tag security  # 보안 회귀 묶음
```

## `check --deploy` 경고 기록

0-2 이후 남은 경고. **0-4 끝에 0으로 만든다.**

| 코드 | 내용 | 해소 단계 |
|---|---|---|
| security.W002 | X-Frame-Options 미들웨어 없음 | 0-4 |
| security.W004 | `SECURE_HSTS_SECONDS` 미설정 | 0-4 |
| security.W008 | `SECURE_SSL_REDIRECT` 미설정 | 0-4 |
