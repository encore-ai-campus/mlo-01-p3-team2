from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.utils import timezone


NEW_PASSWORD = forms.PasswordInput(attrs={"autocomplete": "new-password"})  # 비밀번호 관리자가 칸을 구분한다


class SignupForm(forms.Form):
    """입력 변환만 한다. 규칙 판단(형식·비밀번호 정책·중복)은 foundation 서비스가 한다."""

    username = forms.CharField(label="아이디", max_length=64, strip=False, widget=forms.TextInput(attrs={"autocomplete": "username"}))
    password = forms.CharField(label="비밀번호", widget=NEW_PASSWORD, strip=False, max_length=128)
    password_confirm = forms.CharField(label="비밀번호 확인", widget=NEW_PASSWORD, strip=False, max_length=128)
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

    current_password = forms.CharField(label="현재 비밀번호", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}), strip=False, max_length=128)
    new_password = forms.CharField(label="새 비밀번호", widget=NEW_PASSWORD, strip=False, max_length=128)
    new_password_confirm = forms.CharField(label="새 비밀번호 확인", widget=NEW_PASSWORD, strip=False, max_length=128)

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
        try:
            return result.astimezone(dt_timezone.utc) if result else result
        except (OverflowError, ValueError):  # 0001-01-01T00:00 KST 는 UTC 로 표현할 수 없다(외부 검토 41d2288 — 500 이었다)
            raise forms.ValidationError("표현할 수 없는 시각입니다.", code="invalid")

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


class CampaignCreateForm(forms.Form):
    """캠페인 만들기(6-9d — 광고는 따로 만든다). 입력 변환만 한다 — 이름·기간·금액 규칙은 서비스(`create_campaign`)가 판단한다.
    `request_key` 는 화면을 그릴 때마다 새 값이고, 서비스가 캠페인 행에 함께 저장해 같은 폼의 다시 보냄으로는 하나만 만든다."""

    name = forms.CharField(label="캠페인 이름", max_length=100, strip=False)
    starts_at = KstDateTimeField(label="시작 시각(KST)")
    ends_at = KstDateTimeField(label="끝나는 시각(KST, 비우면 끝 없음)", required=False)
    daily_budget = forms.IntegerField(label="일예산(포인트)")
    request_key = forms.CharField(max_length=64, widget=forms.HiddenInput)


NEW, EXISTING = "new", "existing"


class AdCreateForm(forms.Form):
    """광고 만들기(6-9d, 설계 §10 "광고 만들기 흐름"): 캠페인 고르기 + 광고(광고그룹) + 소재(새로 올리기 또는 등록된 소재). 입력 변환만 한다 — 위치가
    쓸 수 있는지·금액 범위·이미지 규격·남의 소재는 서비스(`create_ad`)가 판단한다. `request_key` 는 화면을 그릴 때마다 새 값이고, 서비스가 광고그룹 행에 함께
    저장해 같은 폼의 다시 보냄으로는 하나만 만든다."""

    campaign_id = forms.ChoiceField(label="캠페인")
    group_name = forms.CharField(label="광고 이름", max_length=100, strip=False)
    slot_ids = forms.MultipleChoiceField(label="구성", widget=forms.CheckboxSelectMultiple, required=False)
    bid_amount = forms.IntegerField(label="입찰(포인트)")
    creative_source = forms.ChoiceField(label="소재", choices=[(NEW, "새로 올리기"), (EXISTING, "등록된 소재 쓰기")], widget=forms.RadioSelect, initial=NEW)
    creative_id = forms.ChoiceField(label="등록된 소재", required=False)
    title = forms.CharField(label="제목", max_length=200, strip=False, required=False)
    redirect_url = forms.CharField(label="이동 주소(https)", max_length=2048, strip=False, required=False)
    image = forms.FileField(label="이미지", required=False, widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg", "data-preview": "image-preview"}))
    request_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    # 서비스 오류의 위치(`create_ad` 가 부분 이름을 붙인다) → 이 폼의 칸
    POINTERS = {
        "/ad_group/name": "group_name", "/ad_group/slot_ids": "slot_ids", "/ad_group/bid_amount": "bid_amount",
        "/creative": "creative_source", "/creative/title": "title", "/creative/redirect_url": "redirect_url",
    }

    def __init__(self, *args, campaigns=(), slots=(), creatives=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["campaign_id"].choices = [(str(c.campaign_id), c.name) for c in campaigns]
        self.fields["slot_ids"].choices = [(str(s.slot_id), s.name) for s in slots]
        self.fields["creative_id"].choices = [("", "고르세요")] + [(str(c.creative_id), c.title) for c in creatives]
        self.fields["image"].widget.attrs["data-max-bytes"] = settings.ASSET_MAX_BYTES

    def clean(self):
        """어느 쪽 소재인지에 따라 그쪽 입력이 있는지만 본다(입력 모양 — 제목·주소·이미지 규칙은 서비스가 본다)."""
        cleaned = super().clean()
        if cleaned.get("creative_source") == EXISTING and not cleaned.get("creative_id"):
            self.add_error("creative_id", "쓸 소재를 고르세요.")
        if cleaned.get("creative_source") == NEW and not cleaned.get("image"):
            self.add_error("image", "이미지를 고르세요.")
        return cleaned


class CreativeUploadForm(forms.Form):
    """소재 올리기(소재 목록·광고 상세의 "올려서 연결"). 규칙(제목·https·이미지 규격)은 서비스가 판단한다."""

    title = forms.CharField(label="제목", max_length=200, strip=False)
    redirect_url = forms.CharField(label="이동 주소(https)", max_length=2048, strip=False)
    image = forms.FileField(label="이미지", widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg"}))



# ---------------------------------------------------------------- 광고그룹 상세(3-2d) — 동작마다 작은 폼이라, 한 칸을 바꾸는 제출이 다른 칸을 옛 값으로 덮지 않는다

class BidForm(forms.Form):
    """새 입찰(추가만). `expected_version` 은 화면이 본 현재 버전(첫 입찰이면 빈 값) — 그 사이 다른 곳에서 입찰이 바뀌었으면 서비스가 거절한다."""

    amount = forms.IntegerField(label="새 입찰(포인트)")
    expected_version = forms.IntegerField(required=False, widget=forms.HiddenInput)


class GroupNameForm(forms.Form):
    """`updated_at` 은 화면이 본 광고그룹의 마지막 변경 시각 — 그 사이 바뀌었으면 서비스가 거절한다(같은 칸의 옛 제출이 최신 변경을 덮지 않게)."""

    name = forms.CharField(label="광고 이름", max_length=100, strip=False)
    updated_at = forms.DateTimeField(widget=forms.HiddenInput)


class GroupSlotsForm(forms.Form):
    slot_ids = forms.MultipleChoiceField(label="구성", widget=forms.CheckboxSelectMultiple, required=False)
    updated_at = forms.DateTimeField(widget=forms.HiddenInput)

    def __init__(self, *args, slots=(), **kwargs):
        kwargs.setdefault("auto_id", "slots_%s")  # 이름 폼과 같은 화면 — 숨긴 updated_at 의 id 가 겹치지 않게
        super().__init__(*args, **kwargs)
        self.fields["slot_ids"].choices = [(str(s.slot_id), s.name) for s in slots]


class CreativeEditForm(forms.Form):
    """제목·이동 주소. `updated_at` 은 화면이 본 마지막 변경 시각 — 그 사이 바뀌었으면(이미지 교체 포함) 서비스가 거절한다. 바뀐 칸만 넘긴다."""

    title = forms.CharField(label="제목", max_length=200, strip=False)
    redirect_url = forms.CharField(label="이동 주소(https)", max_length=2048, strip=False)
    updated_at = forms.DateTimeField(widget=forms.HiddenInput)

    EDITABLE = ("title", "redirect_url")


class ImageForm(forms.Form):
    """`updated_at` 은 화면이 본 소재의 마지막 변경 시각 — 옛 화면의 교체가 그 사이의 교체를 덮지 않게."""

    image = forms.FileField(label="새 이미지", widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg"}))
    updated_at = forms.DateTimeField(widget=forms.HiddenInput)
