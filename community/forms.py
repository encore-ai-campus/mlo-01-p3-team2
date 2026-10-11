from django import forms

from .models import Comment, Post


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["category", "title", "body"]
        error_messages = {
            "category": {"required": "게시판을 선택해 주세요.", "invalid_choice": "등록된 게시판을 선택해 주세요."},
            "title": {"required": "제목을 입력해 주세요.", "max_length": "제목은 140자까지 입력할 수 있어요."},
            "body": {"required": "내용을 입력해 주세요.", "max_length": "내용은 20,000자까지 입력할 수 있어요."},
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        error_messages = {
            "body": {"required": "댓글을 입력해 주세요.", "max_length": "댓글은 2,000자까지 입력할 수 있어요."},
        }
