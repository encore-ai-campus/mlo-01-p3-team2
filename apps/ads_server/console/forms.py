from django import forms


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
