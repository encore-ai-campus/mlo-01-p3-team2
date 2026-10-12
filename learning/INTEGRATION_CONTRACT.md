# Python/SQL learning integration — pending team contract

Existing integer question/session/answer PKs are preserved. `attempt_uuid` is a new local per-answer UUID; it is not an assertion that an operational quiz_attempt exists. `submission_request_uuid` identifies a retried HTTP request. A successful retry returns the persisted response snapshot; changed content with the same key is rejected.

## Point owner interface

`learning.point_integration.PointGateway.record_correct_attempt` proposes input: platform user UUID (mapping unresolved), attempt_uuid, request UUID, local answer ID, subject, difficulty, type, requested_delta. Proposed confirmed response: ledger_uuid, delta, balance_after, event_uuid. The interface is not called until the team confirms the operational models, DB alias, user mapping and idempotent behavior. Current API points status is `not_connected`; quoted points are eligibility, not paid points.

The owner must identify the actual files containing quiz_attempt, point_wallet, point_ledger and event_outbox. None are invented here. Same-DB submission/wallet/ledger/outbox must be one transaction; different DBs cannot be made atomic with a single Django atomic block. Cross-DB durable delivery and retry ownership remain pending.

## Kafka owner

Confirm topic, serializer, event version and required fields for point_granted. Proposed linkage fields are event_uuid, attempt_uuid, ledger_uuid, delta and balance_after. Persist outbox during the owner's transaction; publish separately; mark sent after ACK; retain event_uuid on retry. No Kafka events are currently published. Contract tests must cover duplicate attempts, outage/rollback, worker crash after ACK and replay, and unique ledger grant per attempt.

## Shared Canvas ownership

Integrated into the latest local campus on 2026-10-12. `learning/` remains separate. The shared renderer receives optional learning-only drawing hooks; existing stairs, city scenery, portals, doors and corrected furniture ordering remain intact. Class1/Python and class2/SQL use their real glass-door crossings and wall signs without changing room geometry. Django inserts learning panels/assets into the map's extension markers and gives each learning asset a content hash; the standalone map stays valid HTML. Main-map movement pauses while the private classroom or question panel is open. Classroom movement uses the configured campus speed. E and the existing down-arrow exit return to the corresponding corridor.

## Data completeness

New dataset has 100 questions (40 Python, 60 SQL). With 20 existing beginner Python questions preserved, the DB has 120 questions, 10 per subject/difficulty/type group. Legacy beginner MC/FB pairs share some question text and need quality review; they are not silently rewritten. Legacy question_code remains nullable until a separate backfill is approved. Remaining 2280 questions are not authored. Strict full-bank validation intentionally fails until every group has 200. Automated structural validation does not certify semantic correctness or difficulty calibration. SQL uses common standard SQL; unsupported/comment-heavy syntax is conservatively not normalized. No submitted code runs in Python or a DB.
