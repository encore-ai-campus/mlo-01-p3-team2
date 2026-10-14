import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    username = models.CharField(max_length=30, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADVERTISER)
    nickname = models.CharField(max_length=20)
    class_label = models.CharField("반", max_length=30)
    is_active = models.BooleanField(default=True)
    session_epoch = models.PositiveIntegerField(default=0, db_default=0)  # 올리면 그 전의 로그인 세션이 모두 끝난다(비활성화 — 다시 활성화해도 돌아오지 않는다). DB 기본값은 이 열을 모르는 옛 마이그레이션 상태의 INSERT 용
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

    def _get_session_auth_hash(self, secret=None):
        """세션 검증 값(Django 의 `get_session_auth_hash`·대체 비밀 키 검증이 모두 이것을 부른다)에 `session_epoch` 를 더한다.
        기본은 비밀번호 해시만 써서, 비활성화했다가 다시 활성화하면 옛 세션 쿠키가 그대로 통했다(외부 검토 3-1d)."""
        key_salt = "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash"
        return salted_hmac(key_salt, f"{self.password}:{self.session_epoch}", secret=secret, algorithm="sha256").hexdigest()

    def __str__(self):
        return self.username


class AppendOnlyError(Exception):
    """추가 전용 기록은 INSERT 만 허용한다. 수정·삭제·덮어쓰기 시도는 예외다."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("추가 전용 기록은 수정할 수 없다.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AppendOnlyError("추가 전용 기록은 수정할 수 없다.")

    def delete(self):
        raise AppendOnlyError("추가 전용 기록은 삭제할 수 없다.")

    def bulk_create(
        self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None
    ):
        """부모와 **같은 명시적 시그니처**로 받는다. `*args` 로 받으면 위치 인자로 넘긴 `update_conflicts` 를 못 본다."""
        if update_conflicts:  # 충돌 시 기존 행을 덮어쓰는 upsert
            raise AppendOnlyError("추가 전용 기록은 upsert 로 덮어쓸 수 없다.")
        return super().bulk_create(
            objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts, update_conflicts=update_conflicts,
            update_fields=update_fields, unique_fields=unique_fields,
        )


class AppendOnlyModel(models.Model):
    """한 번 쓰면 바뀌지 않는 기록(감사 로그·원장·입찰 이력·결정)의 부모.

    `_state.adding` 은 파이썬 인스턴스가 새것인지만 알려 준다 — 같은 PK 의 새 인스턴스는 DB 행을 덮어쓸 수 있다.
    그래서 저장은 **항상 INSERT**(`force_insert`)로만 하고, 기존 행을 건드리는 모든 경로(`save` 의 갱신·`update`·upsert·삭제)를 막는다.
    """

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, force_insert=False, force_update=False, update_fields=None, **kwargs):
        if force_update or update_fields is not None or not self._state.adding:
            raise AppendOnlyError("추가 전용 기록은 수정할 수 없다.")
        super().save(*args, force_insert=True, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("추가 전용 기록은 삭제할 수 없다.")


class AuditLog(AppendOnlyModel):
    """누가·언제·무엇을. 비밀값·개인정보는 기록하지 않는다(audit.record_audit 가 가린다)."""

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)  # FK 가 아니다: 사용자가 바뀌어도 기록은 그대로
    actor_username = models.CharField(max_length=30, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    request_id = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "foundation_audit_log"
