"""관리자 화면의 폼. **입력 변환만** 한다 — 규칙(이름 형식, 하한 ≤ 기준가 ≤ 상한, 유예 범위)은 서비스가 판단한다."""
from django import forms

from masters.api import Audience, PricingUnit

GRACE_CHOICES = [(0, "즉시 만료"), (3600, "1시간"), (86400, "24시간"), (7 * 86400, "7일"), (30 * 86400, "30일")]


class MediaForm(forms.Form):
    name = forms.CharField(label="매체 이름", max_length=100, strip=False)


class SlotForm(forms.Form):
    name = forms.CharField(label="게재 위치 이름", max_length=100, strip=False)
    pricing_unit = forms.ChoiceField(label="과금 단위", choices=PricingUnit.choices, help_text="만든 뒤 바꿀 수 없습니다.")
    audience = forms.ChoiceField(label="보는 사람", choices=Audience.choices,
                                 help_text="개인: 결정 하나를 한 사람이 봅니다. 일괄: 여러 사람이 같은 광고를 봅니다. 만든 뒤 바꿀 수 없습니다.")
    floor = forms.IntegerField(label="하한")
    base = forms.IntegerField(label="기준가")
    cap = forms.IntegerField(label="상한")
    reason = forms.CharField(label="사유", max_length=200, strip=False)


class PolicyValuesForm(forms.Form):
    floor = forms.IntegerField(label="하한")
    base = forms.IntegerField(label="기준가")
    cap = forms.IntegerField(label="상한")
    reason = forms.CharField(label="사유", max_length=200, strip=False)


class PolicyForm(PolicyValuesForm):
    expected_version = forms.IntegerField(widget=forms.HiddenInput)  # 폼을 열 때 본 버전(낙관적 잠금). 그 사이 바뀌었으면 서비스가 거절한다


class SlotVersionsField(forms.Field):
    """일괄 변경에서 고른 슬롯들. 체크박스 값 `<slot_id>:<본 버전>` 목록 → {slot_id: 본 버전}. 슬롯이 있는지·버전이 맞는지는 서비스가 판단한다."""

    widget = forms.SelectMultiple  # 같은 이름의 값을 여러 개 받는다(화면의 체크박스는 템플릿이 그린다)

    def to_python(self, value):
        chosen = {}
        for item in value or []:
            slot_id, sep, version = str(item).partition(":")
            if not sep or not version.isdigit():
                raise forms.ValidationError("고른 게재 위치 값이 올바르지 않습니다. 새로 불러와 다시 고르세요.")
            chosen[slot_id] = int(version)
        return chosen


class BulkPolicyForm(PolicyValuesForm):
    slots = SlotVersionsField(required=False)  # 하나도 고르지 않은 경우는 서비스가 알린다


class KeyIssueForm(forms.Form):
    label = forms.CharField(label="라벨(선택)", max_length=100, required=False, strip=False)


class KeyRotateForm(KeyIssueForm):
    grace_seconds = forms.TypedChoiceField(label="기존 키를 유지할 시간", choices=GRACE_CHOICES, coerce=int, initial=86400)
