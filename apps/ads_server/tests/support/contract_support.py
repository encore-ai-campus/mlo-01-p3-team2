"""provider 계약 테스트 틀(Step 2-1). **계약 파일(OpenAPI)을 원본으로, 실제 응답이 그 계약을 지키는지** 확인한다.

두 가지를 구분한다.
1. **파일 검증**(`test_contract_files`): YAML 이 올바른 OpenAPI 3.1 이고 예시가 스키마를 지키는지. 서버와 무관하다.
2. **응답 검증**(`Contract.response_problems`): 실제 응답의 상태 코드·헤더·미디어 타입·본문을 함께 본다.
   본문은 **닫은 스키마**로 본다(`closed`): 계약은 소비자에게 모르는 응답 필드를 무시하라고 하지만, 서버는 계약에 적힌 필드만 내보내야 한다.

`jsonschema` 는 기본 설정에서 `format`(uuid·date-time·uri 등)을 검사하지 않는다. 여기서는 `FormatChecker` 를 연결하고, 검사 의존성
(`rfc3339-validator`·`rfc3986-validator`)이 빠졌을 때 조용히 건너뛰지 않도록 검사기 자체를 테스트한다(`test_contract_framework`).
"""
import functools
import json
import re

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tests.support.helpers import BASE_DIR

CONTRACTS = BASE_DIR.parent.parent / "docs" / "ads-server" / "contracts"
FORMAT_CHECKER = FormatChecker()


@functools.lru_cache(maxsize=None)
def load_spec(name):
    return yaml.safe_load((CONTRACTS / f"{name}.openapi.yaml").read_text(encoding="utf-8"))


def _media_type(value):
    return (value or "").split(";")[0].strip().lower()


NO_BODY_STATUSES = (204, 304)  # HTTP 가 본문을 금지하는 상태(RFC 9110 §15.3.5·§15.4.5)
ASCII_INT = re.compile(r"-?[0-9]+", re.ASCII)


def cookie_problems(response):
    """응답이 쿠키를 설정하는지. **Django 는 쿠키를 `response.headers` 가 아니라 `response.cookies` 에 따로 담는다**."""
    problems = []
    if "Set-Cookie" in response.headers:
        problems.append("Set-Cookie 헤더가 있다")
    cookies = getattr(response, "cookies", None)
    if cookies:
        problems.append(f"쿠키를 설정했다: {sorted(cookies.keys())}")
    return problems


def closed(node):
    """응답 검사용 사본: `properties` 가 있는 객체 스키마는 **모두 닫는다**(설계 §10 "공개 응답 스키마의 추가 필드", 6-2d).
    공개 스키마가 추가 필드를 허용해도(`additionalProperties` 를 빼거나 `true`) 서버 응답의 내부 값 누출·이름 오타가 여기서 걸린다.
    `properties` 가 없는 자유 형식 객체(`Context`)는 그대로 둔다. `allOf` 로 속성을 나눠 합치는 스키마에는 맞지 않는다(응답 검사를 받는 C1 에는 없다)."""
    if isinstance(node, list):
        return [closed(item) for item in node]
    if not isinstance(node, dict):
        return node
    copy = {key: closed(value) for key, value in node.items()}
    if "properties" in copy:
        copy["additionalProperties"] = False
    return copy


def body_bytes(response):
    """일반 응답과 스트리밍 응답(`FileResponse`: 이미지)의 본문을 모두 읽는다."""
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


class Contract:
    def __init__(self, name):
        self.name = name
        self.spec = load_spec(name)

    # ------------------------------------------------------------ 구조 탐색
    def resolve(self, node):
        """`$ref`(문서 안 `#/...`) 체인을 따라간다."""
        seen = 0
        while isinstance(node, dict) and "$ref" in node:
            seen += 1
            assert seen < 20, "$ref 순환"
            target = self.spec
            for part in node["$ref"].lstrip("#/").split("/"):
                target = target[part]
            node = target
        return node

    def operation(self, path, method):
        return self.spec["paths"][path][method.lower()]

    def operations(self):
        for path, item in self.spec["paths"].items():
            for method, op in item.items():
                if method in ("get", "put", "post", "patch", "delete"):
                    yield path, method, op

    # ------------------------------------------------------------ 스키마 검사
    @functools.cached_property
    def closed_components(self):
        return closed(self.spec["components"])

    def validator(self, schema, components=None):
        root = {**schema, "components": components or self.spec["components"]}  # `#/components/...` 참조가 이 루트 안에서 풀린다
        return Draft202012Validator(root, format_checker=FORMAT_CHECKER)

    def schema_errors(self, schema, instance, close=False):
        """`close=True` 면 스키마와 참조되는 `components` 모두 닫은 사본으로 본다(서버 응답 본문 검사)."""
        validator = self.validator(closed(schema), self.closed_components) if close else self.validator(schema)
        return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:140]}" for e in validator.iter_errors(instance)]

    def named_schema_errors(self, name, instance):
        return self.schema_errors({"$ref": f"#/components/schemas/{name}"}, instance)

    # ------------------------------------------------------------ 응답 검사
    def response_problems(self, path, method, response):
        """실제 응답(`status_code`·`headers`·`content`)이 계약과 어긋나는 곳의 설명 목록(지키면 빈 목록)."""
        problems = []
        responses = self.operation(path, method)["responses"]
        status = str(response.status_code)
        declared = responses.get(status) or responses.get("default")
        if declared is None:
            return [f"문서에 없는 상태 코드 {status} (문서: {sorted(responses)})"]
        declared = self.resolve(declared)

        for name, header in (declared.get("headers") or {}).items():
            header = self.resolve(header)
            value = response.headers.get(name)
            if value is None:
                if header.get("required"):
                    problems.append(f"필수 헤더 {name} 이(가) 없다")
                continue
            schema = header.get("schema", {})
            resolved = self.resolve(schema)
            instance = int(value) if resolved.get("type") == "integer" and ASCII_INT.fullmatch(value) else value  # ASCII 숫자만(전각·아라비아 숫자는 문자열로 남아 실패)
            problems += [f"헤더 {name}: {e}" for e in self.schema_errors(schema, instance)]

        if response.status_code in NO_BODY_STATUSES and body_bytes(response):
            problems.append(f"{status} 응답은 본문이 없어야 한다")

        content = declared.get("content")
        if content:
            media = _media_type(response.headers.get("Content-Type"))
            if media not in content:
                problems.append(f"미디어 타입 {media!r} 이(가) 문서에 없다 (문서: {sorted(content)})")
            else:
                schema = content[media].get("schema")
                if "json" in media and schema is not None:
                    try:
                        body = json.loads(body_bytes(response))
                    except ValueError:
                        problems.append("본문이 JSON 이 아니다")
                    else:
                        problems += [f"본문 {e}" for e in self.schema_errors(schema, body, close=True)]
                        # RFC 9457 §3.1.2: 생성하는 서버는 본문 status 가 HTTP 상태와 같아야 한다
                        if media == "application/problem+json" and isinstance(body, dict) and body.get("status") != response.status_code:
                            problems.append(f"본문 status({body.get('status')!r}) 가 HTTP 상태({response.status_code}) 와 다르다")
                elif not body_bytes(response):
                    problems.append("본문이 비어 있다")
        return problems


class ProviderContractMixin:
    """`TestCase` 에 섞어 쓴다: `self.assertContract(contract, path, method, response)`."""

    def assertContract(self, contract, path, method, response):
        problems = contract.response_problems(path, method, response)
        self.assertEqual(problems, [], f"{method.upper()} {path} → {response.status_code}")

    def assertNoCookies(self, response):
        self.assertEqual(cookie_problems(response), [])
