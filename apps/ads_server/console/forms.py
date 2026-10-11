from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.utils import timezone


class SignupForm(forms.Form):
    """입력 변환만 한다. 규칙 판단(형식·비밀번호 정책·중복)은 foundation 서비스가 한다."""

    username = forms.CharField(label="아이디", max_length=64, strip=False)
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput, strip=False, max_length=128)
    password_confirm = forms.CharField(label="비밀번호 확인", widget=forms.PasswordInput, strip=False, max_length=128)
    nickname = forms.CharField(label="닉네임", max_length=64, strip=False)
    class_label = forms.CharField(label="반", max_length=64, strip=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") and cleaned.get("password_confirm") and cleaned["password"] != cleaned["password_confirm"]:
            self.add_error("password_confirm", "비밀번호가 일치하지 않습니다.")
        return cleaned


class ProfileForm(forms.Form):
    """입력 변환만 한다. 닉네임·반의 규칙은 foundation 서비스(가입과 같은 규칙)가 판단한다."""

    nickname = forms.CharField(label="닉네임", max_length=64, strip=False)
    class_label = forms.CharField(label="반", max_length=64, strip=False)


class PasswordChangeForm(forms.Form):
    """새 비밀번호의 규칙은 서비스(가입과 같은 검증)가 판단한다. 여기서는 확인 칸이 같은지만 본다."""

    current_password = forms.CharField(label="현재 비밀번호", widget=forms.PasswordInput, strip=False, max_length=128)
    new_password = forms.CharField(label="새 비밀번호", widget=forms.PasswordInput, strip=False, max_length=128)
    new_password_confirm = forms.CharField(label="새 비밀번호 확인", widget=forms.PasswordInput, strip=False, max_length=128)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") and cleaned.get("new_password_confirm") and cleaned["new_password"] != cleaned["new_password_confirm"]:
            self.add_error("new_password_confirm", "비밀번호가 일치하지 않습니다.")
        return cleaned


METRICS = [("impressions", "노출"), ("clicks", "클릭"), ("conversions", "전환"), ("spent", "소진 포인트")]


class PeriodForm(forms.Form):
    """대시보드의 기간(최근 N일, 오늘 포함 — 설계 D3-5)과 추세 그래프의 지표. 틀린 값은 기본값으로 본다(조회 화면이라 오류로 막지 않는다)."""

    days = forms.TypedChoiceField(label="기간", choices=[(7, "최근 7일"), (14, "최근 14일"), (30, "최근 30일"), (90, "최근 90일")], coerce=int, required=False)
    metric = forms.ChoiceField(label="그래프", choices=METRICS, required=False)

    DEFAULTS = {"days": 7, "metric": "impressions"}

    def values(self):
        """고른 값. 칸마다 없거나 틀리면 기본값."""
        if self.is_bound:
            self.is_valid()  # 칸별로 검증해 맞는 칸만 cleaned_data 에 남는다
        data = getattr(self, "cleaned_data", {})
        return {name: data.get(name) or default for name, default in self.DEFAULTS.items()}


KST = ZoneInfo("Asia/Seoul")


class KstDateTimeField(forms.DateTimeField):
    """화면의 날짜·시각은 KST 로 읽고 쓴다(브라우저의 `datetime-local` 은 시간대가 없다). 서비스에는 UTC 로 넘긴다."""

    widget = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
    input_formats = ["%Y-%m-%dT%H:%M"]

    def to_python(self, value):
        with timezone.override(KST):
            result = super().to_python(value)
        return result.astimezone(dt_timezone.utc) if result else result

    def prepare_value(self, value):
        return value.astimezone(KST).strftime("%Y-%m-%dT%H:%M") if isinstance(value, datetime) and value.tzinfo else value


class CampaignEditForm(forms.Form):
    """캠페인 수정(이름·일예산·끝나는 시각). 규칙(이름 형식·금액 범위·끝 시각)은 서비스가 판단한다. 바뀐 칸만 서비스에 넘긴다.
    `updated_at` 은 폼을 열 때 본 마지막 변경 시각 — 그 사이 다른 곳에서 바뀌었으면 서비스가 거절한다(옛 폼이 덮어쓰지 않게)."""

    name = forms.CharField(label="캠페인 이름", max_length=100, strip=False)
    daily_budget = forms.IntegerField(label="일예산(포인트)")
    ends_at = KstDateTimeField(label="끝나는 시각(KST, 비우면 끝 없음)", required=False)
    updated_at = forms.DateTimeField(widget=forms.HiddenInput)

    EDITABLE = ("name", "daily_budget", "ends_at")


class ReviewRequestForm(forms.Form):
    message = forms.CharField(label="고친 내용(선택)", max_length=500, required=False, strip=False, widget=forms.Textarea(attrs={"rows": 3}))


class AdCreateForm(forms.Form):
    """광고 만들기(단계 제목이 있는 한 페이지 폼, 설계 D3-3). 입력 변환만 한다 — 단위와 위치가 맞는지·금액 범위·이미지 규격은 서비스(`create_ad`)가 판단한다.
    `request_key` 는 화면을 그릴 때마다 새 값이고, 서비스가 캠페인 행에 함께 저장해 같은 폼의 다시 보냄으로는 하나만 만든다."""

    pricing_unit = forms.ChoiceField(label="과금 단위", widget=forms.RadioSelect)
    campaign_name = forms.CharField(label="캠페인 이름", max_length=100, strip=False)
    starts_at = KstDateTimeField(label="시작 시각(KST)")
    ends_at = KstDateTimeField(label="끝나는 시각(KST, 비우면 끝 없음)", required=False)
    daily_budget = forms.IntegerField(label="일예산(포인트)")
    group_name = forms.CharField(label="광고그룹 이름", max_length=100, strip=False)
    slot_ids = forms.MultipleChoiceField(label="게재 위치", widget=forms.CheckboxSelectMultiple, required=False)
    bid_amount = forms.IntegerField(label="입찰(포인트)")
    title = forms.CharField(label="제목", max_length=200, strip=False)
    redirect_url = forms.CharField(label="이동 주소(https)", max_length=2048, strip=False)
    image = forms.FileField(label="이미지", widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg", "data-preview": "image-preview"}))
    request_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    # 서비스 오류의 위치(`create_ad` 가 부분 이름을 붙인다) → 이 폼의 칸
    POINTERS = {
        "/campaign/name": "campaign_name", "/campaign/starts_at": "starts_at", "/campaign/ends_at": "ends_at", "/campaign/daily_budget": "daily_budget",
        "/ad_group/name": "group_name", "/ad_group/pricing_unit": "pricing_unit", "/ad_group/slot_ids": "slot_ids", "/ad_group/bid_amount": "bid_amount",
        "/creative/title": "title", "/creative/redirect_url": "redirect_url",
    }

    def __init__(self, *args, units=(), slots=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pricing_unit"].choices = list(units)
        self.fields["slot_ids"].choices = [(str(s.slot_id), s.name) for s in slots]
        self.fields["image"].widget.attrs["data-max-bytes"] = settings.ASSET_MAX_BYTES
