"""외부 연결 없이 광고 연결 설정의 입력 경계와 비밀 보호를 검사한다."""

import os
import unittest
from types import MappingProxyType
from unittest.mock import patch

from ad_bridge.api.config import AdsConfig


BASE_URL = "http://127.0.0.1:8001/api/media/v1"
MEDIA_KEY = "unit-test-private-media-key"
SUBJECT_SECRET = "unit-test-subject-secret"


class AdsConfigTests(unittest.TestCase):
    def setUp(self):
        self.environ = {
            "ADS_API_BASE_URL": BASE_URL,
            "ADS_MEDIA_KEY": MEDIA_KEY,
            "ADS_API_TIMEOUT": "5",
            "ADS_SUBJECT_SECRET": SUBJECT_SECRET,
        }

    def test_valid_settings_normalize_base_url_and_timeout(self):
        cases = (
            (f"  {BASE_URL}/  ", "2.5", BASE_URL, 2.5),
            ("https://ads.example.com/api/media/v1", 3,
             "https://ads.example.com/api/media/v1", 3.0),
            ("http://[::1]:8001/api/media/v1/", 0.25,
             "http://[::1]:8001/api/media/v1", 0.25),
        )
        for url, timeout, expected_url, expected_timeout in cases:
            with self.subTest(url=url, timeout=timeout):
                config = AdsConfig(url, MEDIA_KEY, timeout, subject_secret="unit-test-subject-secret")
                self.assertEqual(config.base_url, expected_url)
                self.assertEqual(config.timeout, expected_timeout)
                self.assertIsInstance(config.timeout, float)
                self.assertEqual(config.media_key, MEDIA_KEY)

    def test_each_environment_variable_is_required_and_nonempty(self):
        # 일부 설정만 없어도 암묵적인 기본값으로 다른 광고 서버에 붙지 않아야 한다.
        for name in self.environ:
            for missing_or_blank in (None, "", "   ", "\t"):
                with self.subTest(name=name, value=missing_or_blank):
                    values = dict(self.environ)
                    if missing_or_blank is None:
                        del values[name]
                    else:
                        values[name] = missing_or_blank
                    with self.assertRaises(ValueError) as raised:
                        AdsConfig.from_env(values)
                    self.assertIn(name, str(raised.exception))

    def test_explicit_mapping_is_not_mutated_or_filled_from_process_environment(self):
        original = dict(self.environ)
        ambient = {
            "ADS_API_BASE_URL": "https://other.example.com/api/media/v1",
            "ADS_MEDIA_KEY": "other-process-secret",
            "ADS_API_TIMEOUT": "99",
        }
        with patch.dict(os.environ, ambient):
            config = AdsConfig.from_env(MappingProxyType(self.environ))
            self.assertEqual(config.base_url, BASE_URL)
            self.assertEqual(config.media_key, MEDIA_KEY)
            self.assertEqual(config.timeout, 5.0)
            # 빈 매핑도 명시적 입력이다. 실제 환경변수로 대체하면 안 된다.
            with self.assertRaises(ValueError):
                AdsConfig.from_env({})
        self.assertEqual(self.environ, original)

    def test_from_env_reads_current_process_values_when_mapping_is_omitted(self):
        # Windows 시스템 환경변수는 유지하고 광고용 네 값만 일시 교체한다.
        with patch.dict(os.environ, self.environ):
            first = AdsConfig.from_env()
            with patch.dict(os.environ, {"ADS_API_TIMEOUT": "1.75"}):
                second = AdsConfig.from_env()
        self.assertEqual(first.base_url, BASE_URL)
        self.assertEqual(first.media_key, MEDIA_KEY)
        self.assertEqual(first.timeout, 5.0)
        self.assertEqual(second.timeout, 1.75)

    def test_invalid_api_urls_are_rejected_before_any_request(self):
        invalid_urls = (
            "", None,
            "ftp://ads.example.com/api/media/v1",
            "http:///api/media/v1",
            "http://ads.example.com/",
            "http://ads.example.com/api/media/v2",
            "http://ads.example.com/api/media/v1/decisions",
            "http://user:password@ads.example.com/api/media/v1",
            f"{BASE_URL}?debug=1", f"{BASE_URL}#part",
            f"{BASE_URL}?", f"{BASE_URL}#",
            "http://ads example.com/api/media/v1",
            "http://ads.example.com\\other/api/media/v1",
            "http://ads.example.com/api/\nmedia/v1",
            f"{BASE_URL}\x7f",
            "http://ads.example.com:0/api/media/v1",
            "http://ads.example.com:65536/api/media/v1",
            "http://ads.example.com:not-a-port/api/media/v1",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    AdsConfig(url, MEDIA_KEY, 5, subject_secret="unit-test-subject-secret")

    def test_invalid_media_keys_are_rejected_without_leaking_the_key(self):
        invalid_keys = (
            None, 123, "", " ",
            f" {MEDIA_KEY}", f"{MEDIA_KEY} ",
            f"{MEDIA_KEY}\t", f"{MEDIA_KEY}\n", f"{MEDIA_KEY}\x00",
            f"{MEDIA_KEY}\x7f", f"{MEDIA_KEY}한글",
        )
        for index, key in enumerate(invalid_keys):
            with self.subTest(case=index):
                with self.assertRaises(ValueError) as raised:
                    AdsConfig(BASE_URL, key, 5, subject_secret="unit-test-subject-secret")
                self.assertIn("ADS_MEDIA_KEY", str(raised.exception))
                self.assertNotIn(MEDIA_KEY, str(raised.exception))

    def test_timeout_must_be_finite_positive_and_not_boolean(self):
        invalid_timeouts = (
            True, False, None, "", "not-a-number", 0, -1,
            float("nan"), float("inf"), float("-inf"), "NaN", "Infinity",
        )
        for timeout in invalid_timeouts:
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError) as raised:
                    AdsConfig(BASE_URL, MEDIA_KEY, timeout, subject_secret="unit-test-subject-secret")
                self.assertIn("ADS_API_TIMEOUT", str(raised.exception))

    def test_config_representation_does_not_expose_media_key(self):
        config = AdsConfig(BASE_URL, MEDIA_KEY, 5, subject_secret="unit-test-subject-secret")
        self.assertNotIn(MEDIA_KEY, repr(config))
        self.assertNotIn(MEDIA_KEY, str(config))
        self.assertIn(BASE_URL, repr(config))
        self.assertNotIn(SUBJECT_SECRET, repr(config))
        self.assertNotIn(SUBJECT_SECRET, str(config))

    def test_subject_secret_is_required_and_invalid_values_are_redacted(self):
        # 원문을 노출하거나 공백을 제거해 다른 가명을 만들지 않아야 한다.
        for secret in (None, 123, "", " ", " padded ", "line\nbreak", "secret\x00", "secret\x7f", "\ud800"):
            with self.subTest(case=type(secret).__name__):
                with self.assertRaises(ValueError) as raised:
                    AdsConfig(BASE_URL, MEDIA_KEY, 5, subject_secret=secret)
                self.assertIn("ADS_SUBJECT_SECRET", str(raised.exception))
                self.assertNotIn("padded", str(raised.exception))
                self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
