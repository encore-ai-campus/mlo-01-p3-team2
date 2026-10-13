# Std and Sinker

Kafka의 Raw 메시지를 받아 MongoDB에 보존하고, 계약에 따라 검증·표준화한 뒤 성공한 Std 메시지만 Kafka로 발행하는 Python 서비스다. Kafka와 MongoDB는 별도로 준비된 서버에 연결한다.

## 게시 파일

| 경로 | 역할 |
|---|---|
| `std_and_sinker.py` | 서비스 실행 진입점 |
| `manage_topics.py` | 구독할 Raw 토픽과 대응 Std 토픽 준비 |
| `sinker/` | 설정, 계약 검사, 메시지 처리, MongoDB 저장, Kafka 발행·커밋 |
| `contracts/` | 표준 사전·도메인·라우팅·15개 이벤트 계약·공유 지문 벡터 |
| `requirements.txt` | 설치할 의존성의 고정 버전 |
| `requirements.in` | 직접 사용하는 의존성 목록 |

Git 게시 범위는 서비스 실행 코드와 계약·의존성·이 실행 안내다. `.venv`, `.env`, `.env.*`, Docker 구성, 테스트·더미 도구, 생성 결과는 로컬 작업용으로만 남긴다. 서비스 서버의 접속 정보와 자격 증명은 환경변수 또는 Git에서 제외한 로컬 설정 파일로 제공한다.

## 설치

Python 3.11 이상과 Kafka·MongoDB 접속 환경이 필요하다. 아래 명령은 저장소 루트에서 실행한다. 가상환경은 설치한 컴퓨터에서 생성하며 Git에 포함하지 않는다.

```bash
python3 -m venv pipeline/std_and_sinker/.venv
pipeline/std_and_sinker/.venv/bin/python -m pip install -r pipeline/std_and_sinker/requirements.txt
```

## 연결 설정

아래 다섯 환경변수는 필수다. 예시 호스트는 실제 서버 주소로 바꾼다. 인증 정보는 서비스 실행 환경에서 별도로 제공한다.

```bash
export KAFKA_BOOTSTRAP_SERVERS='broker-1:9092,broker-2:9092,broker-3:9092'
export STD_SINKER_INPUT_TOPICS='raw.account,raw.chat,raw.board,raw.comment,raw.content_usage,raw.movement'
export STD_SINKER_CONSUMER_GROUP_ID='std-and-sinker-v1'
export MONGODB_URI='mongodb://mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0'
export MONGODB_DATABASE='std_sinker'
```

`.env` 파일 없이 위 환경변수만으로 실행할 수 있다. 로컬 설정 파일을 사용할 때는 `--env-file /절대경로/설정파일`을 지정한다. 같은 이름의 값이 둘 다 있으면 환경변수가 우선한다.

| 선택 환경변수 | 기본값·역할 |
|---|---|
| `STD_SINKER_CONTRACTS_DIR`, `STD_SINKER_ROUTES_FILE` | 이 디렉터리의 `contracts/`, `contracts/routes.json`. 다른 경로를 사용할 때는 절대경로 권장 |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest`. 유효한 커밋 위치가 없을 때 적용. `earliest` 또는 `error`만 허용 |
| `KAFKA_DELIVERY_TIMEOUT_SECONDS` | `120`. Std 메시지 발행 ACK 대기 시간 |
| `STD_SINKER_RECORD_RETRIES` | `3`. 한 입력의 I/O 처리 시도 횟수 |
| `STD_SINKER_RETRY_BACKOFF_SECONDS` | `1`. 시도 사이 대기 초 |
| `STD_SINKER_RECOVERY_BACKOFF_SECONDS` | `5`. 연결을 다시 만들기 전 최초 대기 초 |
| `STD_SINKER_RECOVERY_BACKOFF_MAX_SECONDS` | `60`. 복구 대기 상한 초. 유한한 값으로 `0 < 최초 대기 <= 상한 <= 600`이어야 함 |
| `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_CA_LOCATION` | 연결 보안 방식과 CA 경로. 기본 보안 방식은 `PLAINTEXT` |
| `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD` | SASL을 사용하는 서버의 접속 설정 |

상대 계약 경로는 `--env-file`로 지정한 파일의 디렉터리를 기준으로 해석한다. 설정·계약은 시작할 때 읽으며 변경 후 재시작한다. `raw.points`도 계약에 등록되어 있으므로 실제 발행·토픽이 준비되면 구독 목록에 추가할 수 있다.

`latest`는 최초 커밋이 없는 파티션에서 장애 후 재연결할 때 미처리 입력을 건너뛸 수 있어 허용하지 않는다. 기존 설정이 `latest`라면 `earliest`로 변경한다. `error`는 유효한 커밋 위치가 없으면 종료하므로, 처음 실행하는 소비자 그룹에는 기본값인 `earliest`를 사용한다.

## 토픽 준비와 서비스 실행

필수 환경변수를 설정한 터미널에서 실행한다.

```bash
pipeline/std_and_sinker/.venv/bin/python pipeline/std_and_sinker/manage_topics.py
pipeline/std_and_sinker/.venv/bin/python pipeline/std_and_sinker/std_and_sinker.py
```

토픽 준비 명령의 기본값은 토픽당 파티션 3개, 복제 계수 3, 최소 ISR 2다. 필요한 브로커와 생성 권한을 먼저 준비한다. 이 명령은 없는 토픽을 생성하며, 이미 존재하는 토픽의 파티션·복제·ISR 설정을 변경하지 않는다. 구독 목록의 모든 토픽은 `contracts/routes.json`에 있어야 한다.

서비스 실행 명령은 지속적으로 입력을 처리한다. 프로세스 관리 도구에서 같은 명령과 환경변수를 사용해 실행·재시작을 관리한다. 짧은 확인 실행에는 `--max-messages N`과 `--idle-timeout 초`를 사용할 수 있으며 지속 실행에서는 생략한다.

Linux 서버의 systemd 서비스 예시는 다음과 같다. 실행 파일과 설정 파일의 절대경로는 실제 설치 경로로 바꾼다. 설정 파일에는 위 환경변수를 작성한다.

```ini
[Unit]
Description=Std and Sinker
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/절대경로/std_and_sinker/.venv/bin/python /절대경로/std_and_sinker/std_and_sinker.py --env-file /절대경로/std_sinker.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

내부 복구 루프는 실행 중인 프로세스의 I/O 장애를 처리한다. 프로세스 강제 종료·비정상 종료에는 위와 같은 재시작 관리가 필요하고, 서버 재부팅 후에도 시작하려면 서비스를 활성화해야 한다. 인증·설정 오류가 지속되면 재시작만으로 해결되지 않으므로 오류 로그를 확인하고 원인을 수정한다.

## 저장·발행 규칙

- MongoDB `raw_logs`는 최초 Raw 메시지, `std_logs`는 성공·실패 결과를 저장한다.
- JSON·이벤트 ID·MongoDB 표현이 불가능한 입력은 `raw_wrong_receipts`, 같은 ID의 다른 Raw 메시지는 `raw_conflict_receipts`에 보관한다.
- Raw·Std 메시지의 이벤트 ID는 유지한다. `raw_logs._id`와 `std_logs._id`는 `event_uuid`, Std 메시지의 추적 ID는 `std_data.event_uuid`다.
- 성공한 Std 메시지만 라우팅 계약의 출력 토픽으로 발행한다. Kafka key는 `user_uuid`, value는 `{std_manifest, std_data}`다.
- 성공은 MongoDB 저장과 Kafka ACK 후, 검증 실패·격리는 필요한 저장 후에만 Raw offset을 커밋한다. 재시도 가능한 I/O 장애는 현재 입력을 최대 3회 시도하고, 소진하면 연결을 다시 만들며 복구를 계속한다.
- Kafka 재발행은 가능하므로 후속 소비자도 `event_uuid`로 중복을 처리해야 한다.
- 정수 필드는 정수만, 불리언 필드는 불리언만 허용한다. 좌표 `x`, `y`만 유한한 정수·실수를 받아 실수로 표현한다.
- 같은 Raw 메시지와 같은 파서 버전의 결과는 유지한다. 높은 파서 버전은 기존 `FAIL`을 `SUCCESS`로 복구할 때만 결과를 교체한다.

시작 시 연결, Kafka poll, MongoDB 저장, Kafka 발행·offset 커밋에서 발생하는 재시도 가능한 장애는 복구 대상이다. 네트워크 단절·타임아웃·일시적인 브로커 또는 MongoDB 장애는 자동으로 다시 시도한다. 인증·권한·설정·계약 오류, 같은 파서 버전에서 서로 다른 결과가 나온 `ResultConflict` 등은 자동 복구 대상이 아니며 오류로 종료한다.

복구할 때는 Consumer를 먼저 닫아 소비자 그룹을 떠나고 다른 연결도 정리한 뒤 대기한다. 기본 대기는 `5 → 10 → 20 → 40 → 60초`이며 이후에는 60초를 유지한다. 새 연결과 Consumer는 그룹에 커밋된 offset부터 미완료 입력을 다시 처리한다. 입력 처리와 offset 커밋이 성공하면 대기를 최초 값으로 되돌린다. 실패한 입력을 건너뛰거나 같은 파티션의 뒤 입력을 먼저 커밋하지 않는다.

Raw 메시지가 Kafka에 보존되어 있고 Kafka·MongoDB가 복구되면 처리를 다시 진행할 수 있다. 외부 서비스가 계속 중단되거나 Raw 보존 기간이 지난 경우까지 처리 완료를 보장할 수는 없다. 재처리 시 MongoDB는 `event_uuid` 기준으로 기존 결과를 유지하며, 이미 발행된 Std 메시지는 다시 발행될 수 있으므로 후속 소비자도 같은 ID로 중복을 처리해야 한다.

운영에서는 프로세스 실행 상태와 함께 Kafka 소비 지연(lag), Raw 토픽 보존 기간, `I/O recovery waiting` 로그의 지속 발생을 확인하고 알림을 설정한다. `I/O recovered` 로그는 처리·커밋이 다시 성공했음을 나타낸다. 프로세스가 살아 있다는 사실만으로 파이프라인 진행을 판단하지 않는다.

## 발행자와 계약 대조

Raw 지문은 값을 변환하기 전의 `raw_data`, Std 지문은 `std_data`로 계산한다. UTF-8 JSON의 키 정렬·공백 제거·Unicode 보존과 `xxh3_64`를 사용한다. 현재 숫자 표현에서는 `1`과 `1.0`의 지문이 다르다. 실제 플랫폼 발행자와 [공유 지문 벡터](contracts/fingerprint_vectors.json)를 대조해 같은 결과를 만드는지 확인한다.

새 이벤트 유형·필드·버전은 사전, 도메인, 이벤트 계약, 라우팅과 후속 소비자 계약을 함께 갱신한다. `manage_topics.py`와 서비스가 시작할 때 계약 연결을 검사하며 잘못된 계약이면 실행하지 않는다.
