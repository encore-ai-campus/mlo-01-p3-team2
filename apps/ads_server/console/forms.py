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
