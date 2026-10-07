import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "관리자"
    ADVERTISER = "advertiser", "광고주"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, username, password, **extra):
        if not username:
            raise ValueError("username 이 필요합니다.")
        user = self.model(username=username, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username, password=None, **extra):
        extra.setdefault("role", Role.ADVERTISER)
        extra.setdefault("is_superuser", False)
        return self._create(username, password, **extra)

    def create_superuser(self, username, password=None, **extra):
        # 관리자 계정은 가입 화면이 없고 서버 명령으로만 만든다(설계 §5.1).
        extra["role"] = Role.ADMIN
        extra["is_superuser"] = True
        return self._create(username, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """아이디·비밀번호·닉네임·반만 가진다. 이메일·이름 필드는 없다(설계 §5.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=30, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADVERTISER)
    nickname = models.CharField(max_length=20)
    class_label = models.CharField("반", max_length=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["nickname", "class_label"]

    objects = UserManager()

    class Meta:
        db_table = "foundation_user"

    @property
    def is_staff(self):
        """Django admin 접근 자격. 활성 상태의 관리자 역할만."""
        return self.is_active and self.role == Role.ADMIN

    def __str__(self):
        return self.username


class SignupAttempt(models.Model):
    """가입 시도 기록(IP 제한용). 개인 정보는 담지 않는다."""

    ip = models.CharField(max_length=45)  # IPv6 최대 45자
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "foundation_signup_attempt"
        indexes = [models.Index(fields=["ip", "created_at"])]


class AuditImmutableError(Exception):
    """감사 로그는 추가만 한다. 수정·삭제 시도는 예외다."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditImmutableError("감사 로그는 수정할 수 없다.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditImmutableError("감사 로그는 수정할 수 없다.")

    def delete(self):
        raise AuditImmutableError("감사 로그는 삭제할 수 없다.")


class AuditLog(models.Model):
    """누가·언제·무엇을. 비밀값·개인정보는 기록하지 않는다(audit.record_audit 가 가린다)."""

    actor_id = models.UUIDField(null=True, blank=True, db_index=True)  # FK 가 아니다: 사용자가 바뀌어도 기록은 그대로
    actor_username = models.CharField(max_length=30, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    request_id = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "foundation_audit_log"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditImmutableError("감사 로그는 수정할 수 없다.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutableError("감사 로그는 삭제할 수 없다.")
