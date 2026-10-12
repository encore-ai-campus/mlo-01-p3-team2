import re

from django.test import SimpleTestCase, tag

from tests.helpers import BASE_DIR

THREAT_MODEL = BASE_DIR.parent.parent / "docs" / "ads-server" / "threat-model.md"


@tag("security")
class ThreatModelSyncTests(SimpleTestCase):
    """위협 모델(docs/ads-server/threat-model.md)이 인용한 테스트가 실제로 존재해야 한다.

    위협 모델을 갱신했는데 테스트 이름이 바뀌었거나, 테스트를 지웠는데 문서가 그대로면 실패한다(설계 §7 갱신 규칙).
    """

    def test_threat_model_references_existing_tests(self):
        if not THREAT_MODEL.exists():  # 앱만 따로 배포된 환경
            self.skipTest("위협 모델 문서가 없다")
        defined = set()
        for path in (BASE_DIR / "tests").rglob("*.py"):
            defined |= set(re.findall(r"def (test_\w+)", path.read_text(encoding="utf-8")))
        doc = THREAT_MODEL.read_text(encoding="utf-8")
        prefixes = re.findall(r"`(test_\w+_)\*`", doc)  # `test_parse_json_*` 같은 접두사 표기
        cited = set(re.findall(r"`(test_\w+)`", doc))
        missing = sorted(n for n in cited if n not in defined)
        self.assertEqual(missing, [], "위협 모델이 인용한 테스트가 없다")
        for prefix in prefixes:
            self.assertTrue(any(d.startswith(prefix) for d in defined), f"{prefix}* 에 해당하는 테스트가 없다")
        self.assertGreater(len(cited), 30)  # 대조가 공회전이 아님을 확인
