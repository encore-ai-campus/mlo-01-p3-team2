"""계약 **파일** 검증(서버와 무관): 올바른 OpenAPI 3.1 인지, 예시가 스키마를 지키는지, 계약 규칙이 서로 모순되지 않는지."""
from django.test import SimpleTestCase, tag
from openapi_spec_validator import validate

from tests.contract_support import Contract, load_spec

NAMES = ("serving", "console")


class ContractFileTests(SimpleTestCase):
    def test_files_are_valid_openapi_31(self):
        for name in NAMES:
            spec = load_spec(name)
            self.assertTrue(spec["openapi"].startswith("3.1"), name)
            validate(spec)  # 구조·내부 $ref 가 틀리면 예외

    def test_operation_ids_are_unique_and_present(self):
        ids = []
        for name in NAMES:
            for path, method, op in Contract(name).operations():
                self.assertIn("operationId", op, f"{name} {method} {path}")
                ids.append(op["operationId"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_examples_match_their_schemas_including_formats(self):
        checked = 0
        for name in NAMES:
            contract = Contract(name)
            for path, method, op in contract.operations():
                body = (op.get("requestBody") or {}).get("content", {})
                for media, c in body.items():
                    for ex_name, ex in (c.get("examples") or {}).items():
                        checked += 1
                        self.assertEqual(contract.schema_errors(c["schema"], ex["value"]), [], f"{name} {method} {path} request {ex_name}")
                for status, response in op["responses"].items():
                    for media, c in (contract.resolve(response).get("content") or {}).items():
                        for ex_name, ex in (c.get("examples") or {}).items():
                            checked += 1
                            self.assertEqual(contract.schema_errors(c["schema"], ex["value"]), [], f"{name} {method} {path} {status} {ex_name}")
            for rn, r in contract.spec["components"].get("responses", {}).items():
                for media, c in (r.get("content") or {}).items():
                    for ex_name, ex in (c.get("examples") or {}).items():
                        checked += 1
                        self.assertEqual(contract.schema_errors(c["schema"], ex["value"]), [], f"{name} response {rn} {ex_name}")
        self.assertGreater(checked, 10)  # 검사가 공회전이 아님


@tag("security")
class ServingContractRuleTests(SimpleTestCase):
    """C1·C3 의 규칙(설계 §3, 계획 2-2·2-3)이 계약 파일 안에서 서로 맞물리는지."""

    contract = Contract("serving")

    def test_decision_post_documents_every_response_the_rules_require(self):
        """키 없음 401 · 매체 비활성 403 · 없는/타 매체 슬롯 404 · 정상(비활성 슬롯·광고 없음 포함) 201 · 크기·형식·제한."""
        responses = self.contract.operation("/decisions", "post")["responses"]
        self.assertLessEqual({"201", "400", "401", "403", "404", "413", "415", "429", "503"}, set(responses))

    def test_forbidden_means_inactive_media_only_and_other_media_slot_is_not_found(self):
        spec = self.contract.spec
        self.assertIn("매체 비활성", spec["components"]["responses"]["Forbidden"]["description"])
        self.assertNotIn("이 매체의 슬롯이 아님", spec["components"]["responses"]["Forbidden"]["description"])
        self.assertIn("다른 매체의 슬롯", spec["components"]["responses"]["NotFound"]["description"])
        desc = self.contract.operation("/decisions", "post")["description"]
        for needle in ("비활성 슬롯", "403", "404", "ad: null"):
            self.assertIn(needle, desc)

    def test_throttled_and_unavailable_always_carry_retry_after(self):
        for name in ("TooManyRequests", "Unavailable"):
            headers = self.contract.spec["components"]["responses"][name]["headers"]
            self.assertTrue(self.contract.resolve(headers["Retry-After"]).get("required"), name)

    def test_every_response_documents_the_request_id_header(self):
        for path, method, op in self.contract.operations():
            for status, response in op["responses"].items():
                if path.startswith("/assets") or status == "204":
                    continue  # C3 는 최종 사용자 브라우저가 받는 이미지라 헤더 계약이 따로 있다
                headers = self.contract.resolve(response).get("headers") or {}
                self.assertIn("X-Request-ID", headers, f"{method} {path} {status}")

    def test_error_responses_are_problem_json_with_a_shared_schema(self):
        for path, method, op in self.contract.operations():
            for status, response in op["responses"].items():
                if status.startswith(("4", "5")) and not path.startswith("/assets"):
                    content = self.contract.resolve(response).get("content", {})
                    self.assertEqual(list(content), ["application/problem+json"], f"{method} {path} {status}")
                    self.assertEqual(content["application/problem+json"]["schema"], {"$ref": "#/components/schemas/Problem"})

    def test_media_key_security_everywhere_except_health_and_assets(self):
        for path, method, op in self.contract.operations():
            if path in ("/health",) or path.startswith("/assets"):
                self.assertEqual(op.get("security"), [], f"{method} {path}")
            else:
                self.assertNotIn("security", op, f"{method} {path}")  # 전역 MediaKey 를 따른다
        self.assertEqual(self.contract.spec["security"], [{"MediaKey": []}])

    def test_rate_limits_and_confirmed_decisions_are_written_in_the_contract(self):
        text = self.contract.spec["info"]["description"]
        for needle in ("150", "300", "450", "600", "Retry-After", "사전에 정의한 목표 완료", "1~200자"):
            self.assertIn(needle, text)
        self.assertNotIn("열린 항목", text)  # 전환 정의·title 은 확정됐다

    def test_asset_404_text_covers_shared_files(self):
        desc = self.contract.operation("/assets/{asset_name}", "get")["description"]
        self.assertIn("같은 내용의 파일을 쓰는 다른 활성 캠페인", desc)
        self.assertIn("교체된 이전 이미지", desc)
