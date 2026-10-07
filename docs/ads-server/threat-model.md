# 광고 서버 위협 모델

> Status: Approved (2026-10-07, Step 0-0)
> 기준: [ads-server-design.md](ads-server-design.md), [implementation-plan.md](implementation-plan.md)
> 이 문서는 **구현과 함께 갱신한다.** 새 URL·모델·파일 경로·계약이 생기면 해당 위협과 검증 테스트를 이 표에 추가한다.
> 문서가 인용한 테스트가 실제로 존재하는지는 `tests/boundaries/test_threat_model_sync.py`가 검사한다.

---

# 1. 자산

| # | 자산 | 왜 지켜야 하나 |
|---|---|---|
| A1 | 계정·세션 | 탈취되면 광고주의 캠페인·포인트, 관리자 권한이 넘어간다 |
| A2 | 포인트(지갑·원장) | 광고비 역할을 하며 이후 메타버스 포인트와 연계된다 |
| A3 | 소재 파일(이미지)·제목·이동 주소 | 승인 없이 최종 사용자(학습자)에게 그대로 노출된다 |
| A4 | 입찰 정책(하한·기준가·상한) | 노출 경쟁의 규칙. 임의 변경 시 노출이 왜곡된다 |
| A5 | 결정·반응 기록, 원장 | 과금과 분석의 근거. 유실·위조·변조가 없어야 한다 |
| A6 | 노출 대상 UUID(`subject_id`) | 가명 식별자. 이후 개인 맞춤에 쓰이므로 유출·노출을 막는다 |
| A7 | 매체 키 | 서버 간 호출 인증. 유출되면 위조 요청이 가능하다 |
| A8 | 비밀값(`SECRET_KEY` 등), `.env` | 세션·서명·DB 접속의 기반 |
| A9 | 감사 로그 | 관리자·주요 행위의 추적 근거 |

# 2. 행위자

| 행위자 | 설명 | 신뢰 수준 |
|---|---|---|
| 익명 방문자 | 가입 전. 가입·로그인 화면과 이미지 URL에 접근 | 신뢰 없음 |
| 광고주 | 가입자. 자기 캠페인·지갑만 다룸 | 낮음(공개 가입, 승인 없음) |
| 관리자 | 서버 명령으로만 만든 계정. 정책·중단·포인트 조정 | 높음(그러나 행위는 기록) |
| 매체 서버 | 메타버스 백엔드. 키로 인증 | 중간(키 유출·버그 가능) |
| 외부 공격자 | 위 어디에도 속하지 않는 네트워크 상의 존재 | 신뢰 없음 |

# 3. 신뢰 경계

```
[학습자 브라우저] ──(이미지 URL, C3)──▶ ┐
[광고주 브라우저] ──(콘솔, 세션)──────▶ │  광고 서버  ──▶ SQLite / 로컬 파일
[관리자 브라우저] ──(Django admin)───▶ │
[매체 서버]      ──(C1, X-Media-Key)──▶ ┘
```

- 광고주가 입력한 값은 **광고 서버를 거쳐 학습자의 화면**(매체가 렌더)에 도달한다. 이 경로가 §5의 핵심이다.
- 매체 서버는 신뢰하되 **검증한다**(키 인증, 소유 확인, 멱등, 규칙 체인).

# 4. 위협과 대응

대응 단계는 [implementation-plan.md](implementation-plan.md)의 단계 번호다. **검증**에는 완료 증거가 되는 테스트(또는 점검)를 적는다. 아직 구현 전인 단계는 계획된 이름이다.

## 4.1 계정·접근

| # | 위협 | 자산 | 행위자 | 대응 | 단계 | 검증 |
|---|---|---|---|---|---|---|
| T1 | 무차별 대입으로 계정 탈취 | A1 | 익명·공격자 | 5회 실패 시 5분 잠금(아이디+IP), Argon2, 비밀번호 검증기 | 0-2 | `test_locked_after_5_failures`, `test_lock_is_per_username_and_ip`, `test_password_validators_applied`, `test_password_stored_as_argon2` |
| T2 | 대량 가입으로 지급 포인트 수집·스팸 소재 양산 | A2, A3 | 익명 | 가입 시도 IP 제한, 광고주당 캠페인·소재·업로드 상한, 관리자 비활성화. **여러 계정 포인트 수집은 C5 연계 시 재검토** | 0-2, 3 | `test_signup_rate_limit_per_ip`, (3) 쿼터 테스트 |
| T3 | 권한 상승: 가입 폼에 `role` 주입, 광고주가 관리자 화면 접근 | A1, A4 | 광고주 | 가입 서비스가 역할 인자를 받지 않음, 역할별 URL 게이트, 관리자 경로 비공개 | 0-2, 0-3 | `test_signup_ignores_role_field`, `test_advertiser_cannot_open_admin_area`, `test_admin_cannot_open_advertiser_area`, `test_signup_cannot_escalate_role` |
| T4 | 남의 객체 접근(IDOR): 캠페인·광고그룹·소재·원장을 ID로 조회·수정 | A2, A3 | 광고주 | 소유권 헬퍼, 남의 자원은 **404**, 기본 거부, URL 전수 점검 | 0-3, 1 | `test_owned_or_404_hides_others_objects`, `test_every_url_is_protected_or_marked_public` |
| T5 | 세션 탈취·고정 | A1 | 공격자 | `HttpOnly`·`SameSite`·prod `Secure`, 로그인 시 세션 키 재발급, 만료, 로그아웃은 POST만 | 0-2 | `test_cookie_names_and_flags`, `test_session_key_rotates_on_login`, `test_session_expires`, `test_logout_requires_post_and_flushes_session` |
| T6 | 프록시 뒤에서 `X-Forwarded-For` 위조로 잠금 우회 | A1 | 공격자 | 기본은 `REMOTE_ADDR`만 신뢰, 프록시 사용 시 신뢰할 프록시 수를 명시 | 0-2 | 설정 테스트(`test_ip_resolution_ignores_untrusted_xff`) |
| T7 | 관리자 경로 노출·추측 | A1, A4 | 공격자 | `ADMIN_URL_PATH`(prod 기본값 `admin/` 금지), 관리자 역할 외 404 | 0-3 | `test_admin_url_default_rejected_in_prod` |
| T8 | 계정 존재 여부 열거(로그인·가입 오류 문구) | A1 | 익명 | 일반적인 오류 문구 | 0-2 | `test_failed_login_message_is_generic`, `test_duplicate_username_generic_error` |

## 4.2 웹·HTTP

| # | 위협 | 자산 | 행위자 | 대응 | 단계 | 검증 |
|---|---|---|---|---|---|---|
| T9 | 광고주 입력의 XSS(제목 등) | A1, A3 | 광고주 | 템플릿 자동 이스케이프, 인라인 스크립트 금지, CSP, 응답 문자열은 신뢰할 수 없는 값임을 계약에 명시 | 0-4, 2 | `test_csp_header_policy`, `test_no_inline_script_or_style_in_templates` |
| T10 | CSRF | A1, A2 | 공격자 | 전역 CSRF, 예외는 허용 목록 한 곳(`/api/media/`) | 0-4 | `test_csrf_enforced_on_post_views`, `test_csrf_exempt_only_for_allowlisted_prefixes` |
| T11 | 클릭재킹 | A1 | 공격자 | `X-Frame-Options: DENY`, `frame-ancestors 'none'` | 0-4 | `test_security_headers_present` |
| T12 | 거대·기형 요청으로 서버 압박, 입력 오류가 500으로 번짐 | A5 | 외부·매체 | 본문 크기·JSON 깊이 제한, `NaN`/`Infinity` 거부, 입력 오류는 4xx | 0-4, 2 | `test_parse_json_*`, `test_malformed_inputs_never_500` |
| T13 | 캐시로 인한 세션·개인 정보 노출 | A1 | 공격자 | 인증 페이지 `Cache-Control: private, no-store` | 0-4 | `test_authenticated_pages_are_no_store` |
| T14 | 오류 화면의 내부 정보 노출(스택트레이스·SQL) | A8 | 외부 | `DEBUG` 꺼짐, 표준 오류 응답 | 0-4 | `test_error_pages_do_not_leak_internals` |

## 4.3 파일·소재

| # | 위협 | 자산 | 행위자 | 대응 | 단계 | 검증 |
|---|---|---|---|---|---|---|
| T15 | 위장 파일 업로드(확장자 조작, 실행 파일, SVG의 스크립트) | A3 | 광고주 | 내용으로 형식 판별(JPEG·PNG만), 재인코딩, 해시 이름 | 0-5 | `test_format_decided_by_content_not_extension`, `test_rejects_svg_gif_webp_bmp`, `test_rejects_text_file_renamed_to_png` |
| T16 | 압축 폭탄·초대형 파일로 메모리·디스크 소진 | A5 | 광고주 | 용량 상한(초과분은 끝까지 읽지 않음), **선언된 요청 길이가 상한을 크게 넘으면 본문을 읽기 전에(CSRF보다 앞에서) 413으로 중단(`RequestBodyLimitMiddleware`), 임시 파일 미생성**, 픽셀 수 상한, 애니메이션 거부 | 0-5 | `test_rejects_over_size_without_reading_all`, `test_oversized_multipart_is_413_with_and_without_csrf_and_leaves_no_temp_files`, `test_declared_content_length_over_limit_is_413_without_reading_the_body`, `test_rejects_decompression_bomb`, `test_rejects_animated_images` |
| T17 | 경로 조작(`..`)·임의 파일 읽기 | A8 | 익명 | URL 정규식으로 형식 제한, 저장 이름은 해시, 사용자 입력 이름 미사용 | 0-5 | `test_path_traversal_returns_404`, `test_name_is_content_hash_and_independent_of_upload_name` |
| T18 | EXIF 위치·기기 정보 등 개인 정보 유출 | A3 | 광고주(본인 모르게) | 재인코딩으로 메타데이터(EXIF·ICC·XMP·텍스트·dpi 등) 제거: **ICC로 sRGB 변환 후 픽셀만 새 이미지로 옮겨 저장**(색 손실 없음). 신뢰할 수 없는 프로필은 열기 실패·색 공간 불일치 시 변환 없이 처리 | 0-5 | `test_reencode_strips_exif`, `test_reencode_strips_png_icc_profile_and_other_ancillary_chunks`, `test_reencode_strips_jpeg_icc_profile`, `test_png_alpha_is_preserved_after_cleaning`, `test_wide_gamut_png_is_converted_to_srgb_not_just_stripped`, `test_unusable_profiles_are_treated_as_srgb_and_do_not_fail_the_upload` |
| T19 | 중단된 소재가 계속 보임(캐시 잔존) | A3 | 학습자 | `Cache-Control: no-cache` + `ETag`, 중단 시 404 | 0-5, 1 | `test_etag_and_304`, `test_cache_control_no_cache_on_200_and_304`, `test_servable_check_false_returns_404` |
| T20 | 쓰기 중인 파일이 노출·반쯤 쓴 파일 | A3 | 시스템 | 임시 파일 + `os.replace`로 확정 | 0-5 | `test_atomic_write_leaves_no_partial_file` |
| T27 | **조작된 ICC 프로필로 색 변환 라이브러리(Pillow 번들 lcms2)를 공격**: 파싱 오류·메모리 소진·크래시. 이미지를 sRGB로 변환하면서 생긴 공격면(2026-10-07 추가) | A3, A5 | 광고주 | ① 업로드 용량 상한 안의 입력만 도달 ② PNG `iCCP`의 압축 해제 폭탄은 Pillow가 한도를 넘으면 거부 → `corrupt` ③ **프로필 1MiB 초과는 lcms에 넘기지 않음**(sRGB 간주) ④ 프로필 열기·색 공간 불일치·변환 오류는 모두 잡아 sRGB로 간주(업로드는 거부하지 않음) ⑤ 이미 sRGB인 프로필은 변환 생략 ⑥ 변환 결과만 저장하고 프로필은 버림 ⑦ `pip-audit`가 Pillow(lcms2 포함) 취약점 점검. **lcms2 자체의 미발견 취약점은 막지 못한다 → §6 잔여 위험** | 0-5 | `test_unusable_profiles_are_treated_as_srgb_and_do_not_fail_the_upload`, `test_oversized_icc_profile_is_not_parsed_and_upload_still_works`, `test_png_icc_decompression_bomb_is_rejected_cleanly`, `test_wide_gamut_png_is_converted_to_srgb_not_just_stripped`, `test_srgb_profile_leaves_pixels_untouched` |

## 4.4 시스템·운영

| # | 위협 | 자산 | 행위자 | 대응 | 단계 | 검증 |
|---|---|---|---|---|---|---|
| T21 | 비밀값 유출(저장소 커밋, 기본값 사용) | A8 | 개발자 | 환경변수·`.env`만, `.env` 미커밋, prod는 키가 없으면 기동 실패 | 0-1 | `test_prod_requires_secret_key`, `.gitignore` 점검 |
| T22 | 로그에 비밀번호·키·세션 기록 | A1, A7, A8 | 시스템 | 본문·민감 헤더 미기록, 로그 필터 | 0-6 | `test_logs_never_contain_password_or_keys` |
| T23 | 관리자 행위 추적 불가 | A9 | 관리자 | 추가 전용 감사 로그(비밀 키 제거). **INSERT 전용 저장**: 같은 PK 새 인스턴스·`force_update`·upsert로 기존 행을 덮어쓸 수 없음. 관리자 본인의 비밀번호 변경·타인 초기화도 기록 | 0-6 | `test_audit_log_is_append_only`, `test_existing_row_cannot_be_overwritten_by_a_new_instance_or_upsert`, `test_audit_detail_strips_secret_keys`, `test_signup_and_login_events_recorded`, `test_own_password_change_is_audited_once_without_the_password` |
| T24 | 취약한 의존성 | 전체 | 외부 | 패치 버전 고정, `pip-audit`, `bandit` | 0-6 | `scripts/check.sh` |
| T25 | 커밋이 디스크에 안 내려가 정전 시 반응 유실 | A5 | 환경 | SQLite WAL + `synchronous=FULL`, 저장 후 확인 | 0-1, 2 | `test_sqlite_pragmas`, (2) 부하 테스트 |
| T28 | **입찰 정책(A4)의 임의·동시·우회 변경**: 노출 경쟁 규칙이 왜곡되거나, 두 관리자가 서로의 변경을 모르고 덮어씀 (1-1에서 추가) | A4 | 관리자·개발자 | ① 변경은 관리자 전용 서비스 함수만(비관리자·비활성·익명 거부) ② **DB `CHECK`**: `0 < 하한 ≤ 기준가 ≤ 상한 ≤ 최대값`(서비스를 우회해도 유지) ③ 정책은 **추가 전용**(수정·삭제·같은 PK 덮어쓰기·upsert 불가) ④ **`expected_version`** 불일치는 `stale_version`(SQLite 직렬 쓰기에서도 동시 저장 중 한쪽만 성공) ⑤ 일괄 입력은 전부 아니면 전무 ⑥ 모든 변경이 이전 값과 함께 감사 로그에 남음(요청 ID 포함) ⑦ Django admin 등록은 읽기 전용이라 서비스 규칙을 우회하지 못함 | 1-1 | `test_non_admin_actor_rejected`, `test_policy_check_constraint_in_db`, `test_policy_is_append_only`, `test_policy_cannot_be_overwritten_by_existing_pk`, `test_policy_stale_expected_version_rejected`, `test_concurrent_policy_saves_only_one_wins`, `test_bulk_policy_is_all_or_nothing`, `test_admin_actions_are_audited_with_request_id`, `test_slot_pricing_unit_immutable` |
| T29 | **종료·중단·예산 소진·잔액 부족 캠페인이 계속 노출**되거나 과금 한도를 넘음 (1-4에서 추가) | A2, A5 | 시스템·광고주 | 자격 필터가 선택 시점에 **판정 근거 값(상태·기간·남은 예산·잔액)을 적용 금액과 비교**한다. 종료 판정은 저장된 상태가 아니라 기간(`is_expired`, 종료 시각 포함)이라 **상태 갱신이 늦어도** 막힌다. 판정 로직은 `engine` 순수 함수 한 곳이고, 입력 타입은 정수·UTC가 아니면 생성 단계에서 거부한다 | 1-4 | `test_each_filter_rejects_with_reason`, `test_stale_active_campaign_past_end_is_rejected_by_period`, `test_budget_and_balance_boundary`, `test_budget_and_balance_use_applied_amount_not_bid`, `test_is_expired_boundaries`, `test_types_reject_bad_values` |
| T26 | 경계 규칙이 무너져 보안 로직이 흩어짐 | 전체 | 개발자 | 경계 검사 테스트, 모델 규약 테스트 | 0-6 | `test_layer_rules`, `test_only_api_imports_across_modules`, `test_all_models_have_explicit_db_table` |

# 5. 두 개의 핵심 경로

## 5.1 광고주가 입력한 값이 학습자에게 닿는 경로 (무승인 공개 집행)

관리자 승인이 없으므로, 광고주가 만든 소재가 **즉시** 학습자 화면에 나간다. 막을 것과 막지 못하는 것을 구분한다.

| 입력 | 위험 | 대응 | 남는 위험 |
|---|---|---|---|
| 이미지 | 부적절한 이미지, 위장 파일, 개인 정보 | 형식·재인코딩(T15~T18), **사후 중단**과 이미지 404(T19) | **내용의 부적절함은 사후에만 잡는다.** 관리자가 보기 전까지 노출될 수 있다 |
| 제목 | XSS, 사칭·욕설 | 길이 제한, 이스케이프 계약, CSP | 내용 검열은 하지 않는다 |
| 이동 주소 | **피싱·악성 사이트** | `https`만, 길이 제한, 관리자 모니터링에 **도메인 표시**, 중단 | **도메인 평판은 확인하지 않는다.** 정상 `https` 사이트로 위장한 피싱은 사후 신고·모니터링으로만 잡는다 |
| 업로드 총량·개수 | 저장소 소진 | 광고주당 상한 | |

**운영 대응**: 관리자 모니터링 화면에서 최근 등록·변경된 소재의 **썸네일과 이동 주소 도메인**을 한눈에 보고, 문제 시 **즉시 중단**(이미지는 404). 광고주는 고친 뒤 **재검토 요청**을 낸다. 가입 지급 포인트가 있어 공개 가입 계정이 쉽게 늘 수 있으므로 계정 비활성화 수단을 둔다.

## 5.2 반응 위조·중복으로 포인트가 오가는 경로

반응(노출·클릭·전환)이 **곧 포인트 차감**이다. 틀린 반응이 광고주의 잔액을 깎거나 통계를 부풀린다.

| 위협 | 대응 | 단계 |
|---|---|---|
| 매체 키 유출 후 위조 요청 | 키 해시 저장, 교체(두 키 동시 유효 기간), 매체별 요청 제한 | 2 |
| 다른 매체의 `decision_id`로 보고 | 규칙 `same-media` | 2 |
| 같은 반응 재전송(네트워크 재시도) | 멱등: (매체, `reaction_id`) 유니크 → 한 번만 처리·과금 | 2 |
| 같은 결정에 노출을 여러 번 보고 | 규칙 `once-per-type` | 2 |
| 존재하지 않는 결정에 보고 | 규칙 `known-decision`, 접수는 하되 `REJECTED`로 보존 | 2 |
| 접수 후 유실 | 저장 후 확인(`synchronous=FULL`), inbox 분리, 재처리 | 0-1, 2 |
| 처리 중 장애로 이중 과금 | 과금은 `reaction_id`당 최대 1번(유니크), 별도 트랜잭션 | 1-3, 2 |
| 원장 변조 | 추가 전용, 잔액=원장 합계 점검 | 1-3 |
| 결정 이후 입찰이 바뀌어 과금액이 달라짐 | 과금액은 Decision에 기록된 적용 금액 | 1-5, 2 |

**남는 위험**: 매체 서버가 **정상 키로 거짓 반응을 보내는 경우**(예: 실제로 보여주지 않은 노출 보고)는 광고 서버가 알 수 없다. 매체와 신뢰 관계로 다룬다.

# 6. 수용하는 잔여 위험

| 위험 | 이유 | 재검토 시점 |
|---|---|---|
| 관리자 2단계 인증 없음 | 범위 결정(Step 0 제외) | 관리자 계정이 늘거나 외부 노출 시 |
| TLS·WAF는 인프라 소관 | `platform/` 담당 | 배포 설계 시 |
| 무승인 집행으로 부적절 소재가 사후에 중단됨 | 서비스 편의 결정 | 신고·남용이 늘면 승인 단계 재검토 |
| 이메일이 없어 비밀번호 분실은 관리자 초기화 | 개인 정보 최소화 결정 | 사용자 수가 늘면 |
| SQLite 단일 노드(쓰기 직렬) | V1 결정 | 부하 테스트(Step 2-6)에서 한계가 보일 때 |
| 가입 지급 포인트의 다중 계정 수집 | 포인트가 외부 가치와 연결되기 전까지 영향 작음 | 메타버스 포인트 연계(C5) 시 |
| **조작된 ICC 프로필이 lcms2의 미발견 취약점을 건드림(T27)** | sRGB 변환은 색 정확도(사용자 경험)를 위해 선택했고, 공개 가입이라 업로더는 신뢰할 수 없다. 입력 크기·프로필 크기를 제한하고 오류를 모두 잡지만 네이티브 라이브러리 내부는 막을 수 없다 | **Pillow 보안 공지·업그레이드 시마다**, 또는 이미지 처리를 별도 프로세스·권한으로 격리할 때(배포 설계). 부담이 커지면 "프로필이 있으면 변환 없이 폐기"로 후퇴할 수 있다 |

# 7. 이 표를 갱신하는 규칙

1. 새 URL·모델·파일 경로·외부 계약이 생기면 **해당 위협 행을 먼저 추가**하고 검증 테스트를 정한다.
2. 위협 행의 **검증 테스트가 통과**해야 해당 단계를 완료로 본다.
3. 사고·결함이 발견되면 이 표에 위협으로 추가하고 재발 방지 테스트를 붙인다.
