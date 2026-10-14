# ads_frontend

광고 서버의 **프론트**(설계 [§6.6 "6-15 분리"](../../docs/ads-server/ads-server-design.md)). DB 가 없는 Django 로, 백엔드([../ads_server](../ads_server/README.md))와 **같은 경로·URL 이름**으로 요청을 받아
그대로 백엔드로 넘기고(입력·쿠키·CSRF 토큰), 돌아온 화면 데이터(`{"presentation": {template, context}}`)를 템플릿으로 그린다. 판단(CSRF·로그인·권한·검증)은 모두 백엔드가 한다.

- **그리는 화면**: 광고주 콘솔, 로그인·가입·잠금, 오류 화면, 운영 화면(Django admin 의 템플릿을 상속 — 그 한국어 문구는 `LOCALE_PATHS`).
- **통과시키는 것**: Django admin 자체, 이미지(`/assets/`), 클릭 이동(`/c/`), 내 소재 이미지 파일 — 백엔드 응답 그대로. **매체 API(`/api/media/`)는 404**(공개하지 않는다).
- **같은 것을 데이터로 갖는다**: 경로 표 `ui/routes.py`, 이름표 `ui/labels.py`, KST 표시 `ui/templatetags/kst.py` — 백엔드 시험(`tests/dev/test_frontend_sync.py`)이 두 쪽이 같은지 본다.
  백엔드 시험은 화면 데이터를 이 렌더러(`ui/rendering.py`)로 그려 HTML 을 본다.

## 실행

```bash
pip install -r requirements.txt          # 백엔드와 같은 가상환경이면 이미 들어 있다
cp .env.example .env                     # BACKEND_URL·ADMIN_URL_PATH(백엔드와 같게)·FRONTEND_ALLOWED_HOSTS
FRONTEND_DEBUG=1 python manage.py runserver 127.0.0.1:8001
```

함께 띄우려면 백엔드 폴더의 `python tests/tools/run_split.py`(백엔드 8000 + 프론트 8001).

## 운영

- 프론트 서버의 nginx(TLS·허용 목록) 뒤에 127.0.0.1 로 연다. `FRONTEND_DEBUG=0` 이면 `FRONTEND_SECRET_KEY`(50자 이상)가 필수다.
- `BACKEND_URL` 은 백 서버의 내부 주소(경로 없이). `ADMIN_URL_PATH`·`ASSET_MAX_BYTES` 는 백엔드와 같게 — 본문이 업로드 상한 + 64KiB 를 넘으면 백엔드로 보내지 않고 413 이다.
- `X-Forwarded-For` 에 받은 상대 주소를 덧붙여 넘긴다 — 백엔드의 `TRUSTED_PROXY_COUNT` 는 2(nginx·프론트).
- 정적 파일: `python manage.py collectstatic --noinput` → 재시작(WhiteNoise 가 시작할 때 `STATIC_ROOT` 를 읽는다). Django admin 의 정적 파일도 여기서 서빙한다.
- 점검: 백엔드의 `tests/tools/check.sh` 가 이 앱의 `check --deploy`·시험·Bandit 도 돌린다. 시험만: `python manage.py test`.
