# EC2 Driver deployment assets

These assets assume a separately verified Spark 4.2.0 standalone cluster with a supported Java 17, 21, or 25 runtime,
the same Python environment on all three Workers, and the pinned JARs from
`runtime_lock.json` under each deployed application's `jars/` directory.

`spark-pipeline.service` runs on spark-1 as the `spark` user. Its foreground
`spark-submit --deploy-mode client` process is the Driver. The two Master addresses
select the active Master; the Master schedules three one-core, 2 GiB Executors on
the three Workers. The Driver heap is 1 GiB. Driver RPC, Driver block transfer, and
Executor block transfer use TCP 7078, 7080, and 7079 respectively; the existing
Worker RPC port remains 7100. Verify connectivity before installing this service.

Deploy an immutable source release under `/opt/pipeline/spark/releases/` and point
`/opt/pipeline/spark/current` to it. The unit uses
`/opt/pipeline/spark/.venv/bin/python`; an existing compatible environment may be
linked to that path. `SPARK_PIPELINE_PYTHON` sets the Python executable used by the
Driver and remote Executors. `SPARK_SUBMIT` can override `/opt/spark/bin/spark-submit`.

Create `/etc/spark-pipeline/pipeline.env` from `pipeline.env.example`, filling in
verified endpoints. Keep password values out of this file. Production subscribes
to seven Std topics including `standardized.points`, starting at `earliest` only
when its checkpoint is new. `POINT_GRANTED` events are written to `point_grant_fact`.
For an existing deployment, append `standardized.points` to `SPARK_INPUT_TOPICS`
in `/etc/spark-pipeline/pipeline.env` and restart `spark-pipeline.service`.

The unit uses `LoadCredentialEncrypted` to decrypt the host's encrypted credential
at `/etc/credstore.encrypted/spark-pipeline-mysql` into systemd's private RAM
credential directory. Its credential name must be `mysql-password`. Provision the
encrypted input through stdin using `systemd-creds encrypt --name=mysql-password`;
never place the plaintext in a command argument, environment file, or disk file.
Verify support for `LoadCredentialEncrypted` and host-key encryption before using
the unit. `launch.py` reads the RAM credential and passes `MYSQL_PASSWORD` only in
the launched Driver's process environment. It verifies each pinned JAR before
launching. The unit restarts the Driver and retains the checkpoint under
`/var/lib/spark-pipeline/checkpoints/std-to-mysql`.

The existing EC2 `spark-env.sh` sets `SPARK_LOCAL_DIRS=/opt/pipeline/spark/tmp`.
The service permits writes to that Spark scratch directory as well as its own
state directory; source releases and configuration remain read-only to the Driver.

## Isolated end-to-end fixture

Generate locally using an environment with the existing Spark requirements:

```sh
pipeline/spark/.venv/bin/python pipeline/spark/deploy/make_smoke_fixture.py \
  --output /private/tmp/spark-smoke-run \
  --topic spark_smoke_RUN \
  --database spark_smoke_RUN \
  --runtime-directory /var/lib/spark-pipeline/smoke/RUN
```

The generator standardizes the existing 15 successful Raw event-type fixtures,
randomizes all UUIDs while preserving shared identifiers, and recalculates the Std
fingerprints. It validates all 18 generated messages: 15 valid events, one exact
duplicate, one bad checksum, and one malformed JSON input. Its registry routes all
15 schemas through the isolated topic. `expected_rows.json` contains the precise
15 fact rows and two error rows; `manifest.json` includes per-table counts.

Create a fresh one-partition test topic with replication factor three and a fresh
test database, migrate that database, then copy the generated files to the runtime
directory. Create a separate smoke environment by merging the production settings
with `smoke.env.fragment` (the fragment must override matching keys). Publish
`producer.lines` once using the Kafka installation's console producer:

```sh
kafka-console-producer.sh --bootstrap-server VERIFIED_BROKER:9092 \
  --topic spark_smoke_RUN \
  --producer-property acks=all --producer-property enable.idempotence=true \
  --property parse.headers=true --property parse.key=true \
  --property headers.separator=, --property headers.key.separator=: \
  < producer.lines
```

The default header delimiter and key separator are literal tabs. Every generated
line is `event_type:VALUE,std_schema_version:1.0<TAB>USER_UUID<TAB>JSON`.
All expected offsets assume the new topic starts at zero and the file is published
exactly once. Use a transient systemd unit with the same credential and service
identity to invoke `launch.py --env-file /path/to/smoke.env --available-now --report
/var/lib/spark-pipeline/smoke/RUN/report.json`. Do not run the production service at
the same time: Driver ports and Executor resources are deliberately fixed.

Compare MySQL rows to `expected_rows.json` (normalize retrieved MySQL datetimes to
`YYYY-MM-DD HH:MM:SS.ffffff` and booleans to true/false). Require three live
Executors in the completed report. Repeat the same available-now job with the same
checkpoint; it must report zero input rows, the same query ID, and unchanged table
contents. After successful verification remove only the isolated topic, database,
checkpoint, and transient unit, then start the production service.

## EC2 Driver 작업 제출 방식

`spark-1`의 systemd 서비스 `spark-pipeline.service`가 `launch.py`를 실행한다.
런처는 RAM에 제공된 MySQL 자격 증명을 읽고 JAR 체크섬을 확인한 뒤 아래 형태로
`spark-submit`을 실행한다. `client` 모드이므로 Driver는 `spark-1`에 계속 실행되고,
활성 Master가 세 Worker에 Executor를 하나씩 배치한다.

```sh
/opt/spark/bin/spark-submit \
  --master spark://10.30.10.113:7077,10.20.10.174:7077 \
  --deploy-mode client \
  --driver-memory 1g \
  --executor-memory 2g --executor-cores 1 --total-executor-cores 3 \
  --jars <체크섬을_확인한_10개_JAR> \
  <Driver와_Executor의_고정_포트_및_Python_설정> \
  /opt/pipeline/spark/current/stream.py \
  --env-file /etc/spark-pipeline/pipeline.env
```

Master는 `spark-1/2`, Driver는 `spark-1`, Worker는 `spark-1/2/3`이다.
Master의 활성·대기 역할은 ZooKeeper 선출 결과에 따라 바뀐다. Driver의 자동
재시작은 `spark-1`의 systemd가 담당하며, 다른 서버로의 Driver 자동 이전은 없다.
각 Executor는 자기 서버의 MySQL Router `127.0.0.1:6446`으로 쓰기 Primary에 접속한다.
새 checkpoint의 최초 위치는 `earliest`이며 재시작은 기존 checkpoint의 기록을 따른다.

```sh
ssh spark-1 'sudo systemctl status spark-pipeline.service --no-pager'
ssh spark-1 'sudo journalctl -u spark-pipeline.service -n 80 --no-pager'
ssh spark-1 'sudo systemctl restart spark-pipeline.service'
```
