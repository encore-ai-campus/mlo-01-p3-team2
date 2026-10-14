"""모든 화면 시험은 화면 데이터를 실제 프론트 렌더러로 그려 본다(tests/support/presentation.py, 설계 §6.6 "6-15 분리").
시험 모듈보다 먼저 읽혀(패키지) `self.client` 와 `from django.test import Client` 가 같은 클라이언트가 되게 한다."""
import django.test

from .support.presentation import PresentationClient

django.test.SimpleTestCase.client_class = PresentationClient
django.test.Client = PresentationClient
