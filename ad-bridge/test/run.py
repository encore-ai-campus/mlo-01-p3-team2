"""게임에 가져갈 코드만 검사한다. 기능별 또는 한 항목씩 선택해 실행한다."""

import argparse
import os
import sys
import unittest
from pathlib import Path


GROUPS = {
    'result_storage': ('test.storage.test_result_storage.ResultStorageTests', {'save': 'test_save', 'terminal': 'test_terminal', 'owner': 'test_owner', 'pending': 'test_pending', 'failure': 'test_failure', 'race': 'test_race'}),
    'results': ('test.results.test_service.ResultServiceTests', {'received': 'test_received', 'accepted': 'test_accepted', 'rejected': 'test_rejected', 'owner': 'test_owner', 'pending': 'test_pending', 'lookup_error': 'test_lookup_error', 'mismatch': 'test_mismatch', 'save_error': 'test_save_error'}),
    'result_client': ('test.results.test_client.ResultClientTests', {'request': 'test_request', 'states': 'test_states', 'uuid': 'test_uuid', 'schema': 'test_schema', 'response': 'test_response', 'http_error': 'test_http_error', 'transport': 'test_transport', 'secret': 'test_secret'}),
    "config": ("test.api.test_config.AdsConfigTests", {
        "valid": "test_valid_settings_normalize_base_url_and_timeout",
        "required_env": "test_each_environment_variable_is_required_and_nonempty",
        "isolated_env": "test_explicit_mapping_is_not_mutated_or_filled_from_process_environment",
        "process_env": "test_from_env_reads_current_process_values_when_mapping_is_omitted",
        "url": "test_invalid_api_urls_are_rejected_before_any_request",
        "key": "test_invalid_media_keys_are_rejected_without_leaking_the_key",
        "timeout": "test_timeout_must_be_finite_positive_and_not_boolean",
        "secret": "test_config_representation_does_not_expose_media_key",
    }),
    "request": ("test.api.test_client.DecisionClientTests", {
        "personal": "test_personal_request_uses_config_and_only_pseudonymous_ids",
        "no_ad": "test_no_ad_and_new_fields_are_supported",
        "shared": "test_shared_omits_subject_and_keeps_click_template",
        "uuid": "test_bad_input_is_rejected_before_network_access",
        "http_error": "test_http_failures_are_exposed_without_retry",
        "error_metadata": "test_non_json_http_failure_keeps_status_and_redacts_metadata",
        "timeout": "test_timeout_connection_and_truncated_response_do_not_retry",
        "success_status": "test_invalid_success_status_or_content_type_is_not_no_ad",
        "schema": "test_missing_wrong_or_mismatched_required_fields",
        "response": "test_invalid_json_oversized_response_and_unsafe_urls_are_rejected",
    }),
    "decisions": ("test.decisions.test_service.DecisionServiceTests", {
        "save": "test_request_is_saved_before_decision_is_returned",
        "storage_error": "test_storage_failure_is_propagated_without_requesting_again",
        "no_ad": "test_no_ad_decision_is_also_saved",
    }),
    "game": ("test.game.test_game_adapter.GameAdapterTests", {
        "identity": "test_success_uses_server_identity_and_returns_only_public_fields",
        "no_ad": "test_no_ad_is_a_successful_decision",
        "login": "test_authentication_and_post_are_required_before_upstream_call",
        "csrf": "test_csrf_middleware_rejects_missing_token_and_accepts_matching_token",
        "missing": "test_missing_slot_or_profile_does_not_call_upstream",
        "invalid_config": "test_invalid_environment_or_uuid_is_a_configuration_error",
        "http_error": "test_upstream_http_error_preserves_status_and_request_id",
        "network_error": "test_transport_and_invalid_response_fail_safely_without_retry",
        "uuid": "test_actual_client_rejects_invalid_server_uuids_before_http",
        "user_switch": "test_actual_client_sends_each_logged_in_profile_to_the_configured_endpoint",
        "storage_error": "test_decision_storage_failure_does_not_return_an_untracked_ad",
    }),
    "impression": ("test.api.test_impression.ImpressionClientTests", {
        "send": "test_first_report_puts_only_impression_and_fixed_time",
        "resend": "test_explicit_same_report_accepts_200_and_preserves_request_bytes",
        "subject": "test_subject_is_normalized_and_sent_when_supplied",
        "uuid": "test_invalid_uuids_are_rejected_before_network",
        "time": "test_invalid_utc_times_are_rejected_before_network",
        "precision": "test_same_time_with_different_fraction_precision_is_accepted",
        "status": "test_known_states_new_fields_and_unknown_reason_are_accepted",
        "required": "test_every_required_response_field_is_checked",
        "schema": "test_wrong_response_types_and_dates_are_rejected",
        "match": "test_response_ids_subject_and_time_must_match_request",
        "http_error": "test_http_failures_preserve_status_without_retry",
        "network_error": "test_transport_failure_before_acknowledgement_does_not_retry",
        "json_ack": "test_malformed_json_after_2xx_retains_acknowledgement",
        "read_ack": "test_body_read_failure_after_2xx_retains_acknowledgement",
        "body_ack": "test_bad_content_type_or_oversized_body_retains_acknowledgement",
        "status_ack": "test_unexpected_2xx_is_acknowledged_but_not_a_valid_reaction",
        "secret": "test_reflected_media_key_is_removed_from_result_and_http_metadata",
        "redirect": "test_redirect_is_blocked_without_following_or_retrying",
    }),
    "impression_service": ("test.impressions.test_impression_service.ImpressionServiceTests", {
        "first": "test_first_report_reserves_stable_payload_before_http",
        "duplicate": "test_acknowledged_duplicate_preserves_uuid_and_time_without_resending",
        "unconfirmed": "test_unconfirmed_duplicate_is_not_retried_in_this_step",
        "sending": "test_existing_sending_reservation_is_not_sent_again",
        "blocked": "test_terminal_http_errors_are_blocked_without_new_reaction",
        "retry_later": "test_retryable_http_errors_remain_unconfirmed_without_immediate_retry",
        "timeout": "test_transport_failure_is_unconfirmed_without_secret_text",
        "malformed_ack": "test_malformed_acknowledged_response_keeps_receipt_and_does_not_resend",
        "malformed": "test_response_without_acknowledgement_is_blocked",
        "invalid_input": "test_invalid_input_is_blocked_without_raw_exception",
        "reserve_fail": "test_reservation_failure_prevents_http",
        "save_fail": "test_save_failure_after_receipt_preserves_reservation_and_prevents_resend",
    }),
    "game_impression": ("test.game.test_game_impression.GameImpressionTests", {
        "identity": "test_server_identity_time_and_reaction_ignore_browser_forgery",
        "duplicate": "test_duplicate_returns_existing_receipt_without_second_http",
        "login": "test_anonymous_request_requires_login_without_sending",
        "post": "test_get_is_rejected_without_sending",
        "csrf": "test_csrf_middleware_rejects_missing_token_and_accepts_matching_token",
        "owner": "test_foreign_or_unknown_decision_is_404_without_sending",
        "no_ad": "test_decision_without_ad_is_409_without_sending",
        "app": "test_storage_app_missing_returns_503_without_sending",
        "profile": "test_missing_profile_uuid_returns_409_without_sending",
        "uuid": "test_invalid_profile_uuid_returns_503_without_sending",
        "http_error": "test_http_failure_returns_state_and_retry_metadata_without_resending",
        "blocked": "test_blocked_http_failure_remains_502_on_duplicate",
        "network": "test_transport_failure_is_unconfirmed_and_does_not_expose_error_text",
        "malformed_ack": "test_acknowledged_invalid_body_returns_202_without_claiming_acceptance",
        "reserve_fail": "test_reservation_database_failure_is_503_before_http",
        "save_fail": "test_database_failure_after_receipt_preserves_uncertainty_and_reservation",
        "route": "test_route_accepts_uuid_and_rejects_malformed_decision_path",
    }),
    "retry": ("test.delivery.test_retry.RetryTests", {
        "due": "test_failed_report_waits_until_due_and_reuses_identical_payload",
        "retry_after": "test_retry_after_remains_a_minimum_even_beyond_backoff_cap",
        "late_retry_after": "test_late_retry_after_from_expired_worker_delays_next_claim",
        "backoff": "test_backoff_doubles_caps_and_handles_very_large_attempt_count",
        "zero": "test_429_retry_after_zero_still_waits_for_local_backoff",
        "completed": "test_retry_delay_starts_after_failed_http_finishes",
        "reschedule": "test_worker_reschedules_transient_failures_using_incremented_attempts",
        "terminal": "test_terminal_http_errors_never_get_new_ids_or_worker_retries",
        "blocked": "test_worker_counts_permanent_failure_as_blocked",
        "lease": "test_expired_sending_lease_is_recovered_with_same_event",
        "legacy": "test_legacy_missing_schedule_or_lease_is_recoverable",
        "malformed_ack": "test_malformed_acknowledged_body_stops_future_puts",
        "malformed": "test_malformed_response_without_acknowledgement_is_blocked",
        "batch": "test_batch_limit_leaves_remaining_records_for_next_run",
        "stop": "test_stop_signal_prevents_claim_and_stops_between_items",
        "save_fail": "test_result_save_failure_recovers_only_after_lease_expiry",
        "policy": "test_policy_rejects_nonpositive_nonfinite_and_boolean_parameters",
        "invalid_delay": "test_delay_rejects_invalid_attempts_and_retry_after",
        "limit": "test_invalid_batch_limit_fails_before_claiming_or_sending",
    }),
    "retry_command": ("test.delivery.test_retry_command.RetryCommandTests", {
        "once": "test_once_dispatches_exactly_one_batch_with_default_options",
        "options": "test_custom_batch_and_interval_are_used",
        "invalid_options": "test_invalid_options_fail_before_config_or_dispatch",
        "config": "test_invalid_config_fails_without_claiming_or_exposing_secret",
        "loop": "test_default_loop_uses_stop_callback_between_batches",
        "stop": "test_first_ctrl_c_finishes_batch_then_stops_and_restores_handler",
        "force_stop": "test_second_ctrl_c_propagates_keyboard_interrupt",
        "once_db": "test_once_database_failure_is_nonzero_and_redacted",
        "reconnect": "test_loop_database_failure_waits_and_reconnects_before_next_batch",
        "idle": "test_idle_batches_do_not_emit_repeated_output",
        "unexpected": "test_unexpected_exception_and_keyboard_interrupt_are_not_swallowed",
        "cleanup": "test_cleanup_database_error_is_redacted",
    }),
    "storage": ("test.storage.test_impression_storage.ImpressionStorageTests", {
        "remember": "test_remember_decision_persists_owner_and_is_idempotent",
        "immutable": "test_existing_owner_and_decision_fields_cannot_be_overwritten",
        "personal": "test_shared_decision_is_rejected_before_storage",
        "owner": "test_missing_and_other_user_decisions_are_not_disclosed",
        "no_ad": "test_no_ad_decision_cannot_create_impression",
        "reserve": "test_first_reservation_fixes_uuid_subject_and_original_timestamp",
        "duplicate": "test_duplicate_reservation_keeps_original_request_after_reload",
        "unconfirmed": "test_unconfirmed_impression_is_preserved_without_creating_a_new_request",
        "finish": "test_finish_changes_only_result_and_does_not_overwrite_first_outcome",
        "ack_unknown": "test_acknowledgement_can_be_saved_without_a_parseable_reaction",
        "unique": "test_database_unique_constraint_prevents_a_second_impression",
        "rollback": "test_failed_transaction_leaves_no_partial_impression",
        "time": "test_invalid_timestamp_is_rejected_without_a_record",
        "metadata": "test_invalid_finish_metadata_does_not_change_pending_request",
        "transaction": "test_outer_transaction_is_rejected_before_reserving",
    }),
    "retry_storage": ("test.storage.test_retry_storage", {
        "reserve": "RetryStorageTests.test_reservation_has_first_attempt_and_active_lease",
        "schedule": "RetryStorageTests.test_due_time_and_retry_metadata_are_persisted",
        "lease": "RetryStorageTests.test_expired_lease_recovers_crashed_sending_record",
        "terminal": "RetryStorageTests.test_terminal_records_cannot_be_claimed",
        "stale_failure": "RetryStorageTests.test_stale_failure_does_not_overwrite_current_owner",
        "late_retry_after": "RetryStorageTests.test_late_retry_after_survives_lease_races_and_shorter_failure_delays",
        "token": "RetryStorageTests.test_missing_token_cannot_finish_a_new_lease",
        "stale_ack": "RetryStorageTests.test_stale_acknowledgement_dominates_current_and_late_failures",
        "blocked_ack": "RetryStorageTests.test_stale_acknowledgement_can_confirm_previously_blocked_request",
        "duplicate": "RetryStorageTests.test_duplicate_notification_does_not_extend_or_replace_lease",
        "legacy": "RetryStorageTests.test_legacy_missing_schedule_or_lease_is_claimable",
        "race": "RetryStorageTests.test_lost_conditional_update_cannot_return_another_workers_lease",
        "rollback": "RetryStorageTests.test_claim_rollback_preserves_previous_schedule",
        "transaction": "RetryStorageTests.test_claim_rejects_external_transaction_before_modification",
        "clock": "RetryStorageTests.test_invalid_clock_and_lease_are_rejected",
        "metadata": "RetryStorageTests.test_diagnostics_reject_exception_text_and_invalid_http_metadata",
        "migration": "RetryMigrationTests.test_migration_recovers_pending_and_preserves_terminal_rows",
    }),
}

STORAGE_GROUPS = {"storage", "retry_storage", "result_storage"}


def main():
    parser = argparse.ArgumentParser(description="게임 연동 단위 테스트 또는 별도 임시 DB 저장소 검사를 선택합니다.")
    parser.add_argument("group", nargs="?", choices=[*GROUPS, "all"], help="검사할 기능")
    parser.add_argument("case", nargs="?", help="한 항목만 검사할 때 --list에 표시된 이름")
    parser.add_argument("--list", action="store_true", help="기능별 단일 테스트 목록 표시")
    args = parser.parse_args()
    if args.list:
        for group, (_, cases) in GROUPS.items():
            print(f"{group} ({len(cases)}개):")
            for case in cases:
                print(f"  {group} {case}")
        return 0
    if not args.group:
        parser.error("--list로 검사할 기능 이름을 확인하고 지정하세요.")
    if args.group == "all" and args.case:
        parser.error("한 항목을 선택할 때는 all 대신 해당 기능을 지정하세요.")
    if args.case and args.case not in GROUPS[args.group][1]:
        parser.error("없는 테스트 항목입니다. --list로 이름을 확인하세요.")

    # 실행 위치와 PYTHONPATH 설정에 관계없이 같은 scripts의 원본 패키지를 검사한다.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if args.group in {"game", "game_impression", "retry_command", "all"} | STORAGE_GROUPS:
        try:
            import django
        except ModuleNotFoundError:
            parser.error("게임 연결 검사는 Django가 필요합니다. 현재 Python으로 -m pip install -r requirements-test.txt를 실행하세요.")
        # 실제 게임/광고 서버 설정이 환경에 있더라도 테스트 전용 설정으로 고정한다.
        os.environ["DJANGO_SETTINGS_MODULE"] = (
            "test.support.django_storage_settings" if args.group in STORAGE_GROUPS else "test.support.django_settings"
        )
        django.setup()

    # all은 단위 테스트만 포함한다. 임시 DB 검사는 저장소 그룹을 명시해야 실행된다.
    selected_groups = [group for group in GROUPS if group not in STORAGE_GROUPS] if args.group == "all" else [args.group]
    labels = []
    for group in selected_groups:
        class_name, cases = GROUPS[group]
        labels.append(f"{class_name}.{cases[args.case]}" if args.case else class_name)
    if args.group in STORAGE_GROUPS:
        from django.test.runner import DiscoverRunner

        # 테스트 전용 메모리 SQLite를 생성·폐기하며 게임/광고 DB 설정을 읽지 않는다.
        return 1 if DiscoverRunner(verbosity=2, interactive=False).run_tests(labels) else 0
    # 네트워크와 로그인 사용자는 각 테스트에서 대체한다. DB 생성은 수행하지 않는다.
    suite = unittest.defaultTestLoader.loadTestsFromNames(labels)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
