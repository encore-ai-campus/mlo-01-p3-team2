from django.conf import settings
from django.db import models
import uuid


class Post(models.Model):
    class Category(models.TextChoices):
        NOTICE = "notice", "공지사항"
        FREE = "free", "자유게시판"
        IT = "it", "IT정보"
        PROJECT = "project", "프로젝트 공유·피드백"
        CAREER = "career", "취업·진로"
        STUDY = "study", "학습자료 공유"
        QUESTION = "question", "질문·답변"

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="community_posts")
    post_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    revision = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices)
    title = models.CharField(max_length=140)
    body = models.TextField(max_length=20000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["category", "-created_at"], name="community_category_date")]


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey(
        "self", to_field="comment_uuid", db_column="parent_comment_uuid",
        null=True, blank=True, on_delete=models.CASCADE, related_name="replies",
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="community_comments")
    comment_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    revision = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]
