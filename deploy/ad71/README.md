# 게임 광고 연결 배포

실행 코드와 설정은 [광고 모듈 안내](../../backend/ad_bridge/README.md)를 따른다. 실제 서버 주소·키·DB·백업과 일회성 배포 기록은 저장소에 포함하지 않는다.

## 적용 범위

- 백엔드: `backend/ad_bridge/`, 광고 앱·URL 설정, `campus/motion.py`와 `campus/consumers.py`의 이동 승인 연결.
- 프론트: 광고 JS 두 파일, `campus.js` 연결, `isometric.js`의 이미지 높이·노출 다각형, `index.html` 스크립트 등록과 `floor-transition.css` 좌우 배치.
- 운영 설정: `backend/.env.example`의 광고 항목만 기존 환경 파일에 병합한다. 키·가명 비밀은 백엔드에서 관리한다.
- 기존 광고 테이블이 없으면 광고 앱의 0001부터 전체 마이그레이션을 적용한다. 기존 데이터가 있으면 DB를 백업하고 이행 계획을 먼저 확인한다.

## 적용 순서

1. 현재 프론트가 사용하는 백엔드 주소와 실행 경로, Nginx 정적 파일 경로를 확인한다.
2. 최신 서버 코드와 배포할 변경을 비교한다. 다른 팀의 수정은 보존하고 코드·환경 파일·DB를 백업한다.
3. 광고를 비활성화한 상태에서 백엔드·프론트 연결을 함께 적용한다. 기존에 없는 `begin_transfer` 명령을 프론트가 먼저 호출하지 않도록 배포 순서를 맞춘다.
4. Django 검사와 마이그레이션을 수행하고 실제 서비스 방식에 맞게 백엔드를 재시작한다.
5. JS·CSS는 프론트 소스와 실제 Nginx 제공 사본에 함께 반영한다. 기존 파일 해시 기반 HTML 버전 처리를 사용한다. 이미 열린 게임 화면은 새로고침해야 한다.
6. 광고 슬롯·키·이미지 HTTPS/CORS를 확인한 뒤 광고를 활성화하고, 옥상·포털 조회와 실제 화면 표시를 확인한다.

기존 구성의 경로 예시는 백엔드 `/home/ubuntu/backend`, 프론트 `/home/ubuntu/frontend/dist`, 수집 사본 `/home/ubuntu/frontend/staticfiles/campus`, Nginx 사본 `/var/www/playdata-campus/static/campus`다. 배포 대상에서 실제 경로를 다시 확인한다.

## 재전송 서비스

함께 제공한 service는 위 백엔드 경로와 `ubuntu` 계정을 사용한다. 다른 환경은 경로·계정을 맞춘 뒤 설치한다. 명령은 저장소 루트에서 실행한다.

```bash
sudo install -m 644 deploy/ad71/playdata-ad-reactions.service /etc/systemd/system/
# 예전 타이머가 설치돼 있으면 끄고 지운다(5초마다 새 프로세스를 띄웠다)
sudo systemctl disable --now playdata-ad-reactions.timer 2>/dev/null; sudo rm -f /etc/systemd/system/playdata-ad-reactions.timer
sudo systemctl daemon-reload
sudo systemctl enable --now playdata-ad-reactions.service
```

서비스는 한 번 떠 있고 5초(`--poll-interval 5`)마다 대기 반응을 기존 ID·가명·시각으로 재전송한다. 예전 타이머 방식은 5초마다 새 Python 프로세스를 띄워 회당 CPU 약 1.1초(하루 종일 코어 하나의 약 17%)를 썼다.
멈출 때는 SIGINT 로 진행 중인 요청의 결과를 저장한 뒤 끝난다. 노출 접수 응답과 최종 인정·차감은 별도로 확인한다.

## 복구

코드·환경 파일은 해당 배포 전 백업을 기준으로 복구한다. `0004_shared_impressions`로 공유 기록이 생성된 뒤에는 이전 코드만 되돌려 실행하지 않는다. DB 백업과 데이터 이행을 포함한 복구 계획을 사용한다.
