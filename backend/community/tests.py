import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Profile
from .models import Comment, Post


class CommunityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(username="community_author", password="Campus!4820")
        self.reader = User.objects.create_user(username="community_reader", password="Campus!4820")
        self.admin = User.objects.create_user(username="community_admin", password="Campus!4820", is_staff=True)
        for user, name in [(self.author, "작성자"), (self.reader, "다른 조원"), (self.admin, "관리자")]:
            Profile.objects.create(user=user, nickname=name)
        self.client.force_login(self.author)
        self.other = Client()
        self.other.force_login(self.reader)
        self.staff = Client()
        self.staff.force_login(self.admin)

    def url(self, name, *args):
        return reverse("community:" + name, args=args)

    def send(self, method, url, data=None, client=None):
        return getattr(client or self.client, method)(url, data=json.dumps(data) if data is not None else "", content_type="application/json")

    def make_post(self, author=None, category="free", title="새 프로젝트를 소개합니다", body="첫 번째 줄\n코드: print('hello')"):
        return Post.objects.create(author=author or self.author, category=category, title=title, body=body)

    def test_anonymous_cannot_read_community(self):
        client = Client()
        item = self.make_post()
        for url in [self.url("metadata"), self.url("posts"), self.url("post-detail", item.pk), self.url("comments", item.pk)]:
            self.assertEqual(client.get(url).status_code, 401)

    def test_anonymous_cannot_create_change_or_delete(self):
        self.assertEqual(self.send("post", self.url("posts"), {"title": "x"}, Client()).status_code, 401)
        item = self.make_post()
        self.assertEqual(self.send("delete", self.url("post-detail", item.pk), client=Client()).status_code, 401)

    def test_incomplete_profile_cannot_access_community(self):
        Profile.objects.filter(user=self.author).update(setup_complete=False)
        self.assertEqual(self.client.get(self.url("metadata")).status_code, 403)
        self.assertEqual(self.send("post", self.url("posts"), {"category": "free", "title": "test", "body": "test"}).status_code, 403)

    def test_categories_counts_and_notice_permissions(self):
        self.make_post(category="project")
        self.make_post(category="project")
        self.make_post(author=self.admin, category="notice")
        data = self.client.get(self.url("metadata")).json()
        self.assertEqual(len(data["categories"]), 7)
        self.assertEqual(data["total"], 3)
        self.assertEqual({c["id"]: c["count"] for c in data["categories"]}["project"], 2)
        self.assertFalse(next(c for c in data["categories"] if c["id"] == "notice")["canWrite"])
        admin = self.staff.get(self.url("metadata")).json()
        self.assertTrue(all(c["canWrite"] for c in admin["categories"]))

    def test_create_and_read_post_use_server_identity_and_plain_text(self):
        body = '<script>alert("x")</script>\n코드: print("안녕")\nhttps://example.com/'
        result = self.send("post", self.url("posts"), {"category": "it", "title": "IT 소식", "body": body, "author_id": self.reader.pk}).json()["post"]
        self.assertEqual(result["author"]["id"], self.author.pk)
        self.assertEqual(result["author"]["nickname"], "작성자")
        self.assertEqual(self.client.get(self.url("post-detail", result["id"])).json()["post"]["body"], body)
        self.assertEqual(Post.objects.get(pk=result["id"]).author, self.author)

    def test_all_posts_and_each_category_can_be_browsed(self):
        for value in Post.Category.values:
            self.make_post(category=value, author=self.admin if value == "notice" else self.author)
        self.assertEqual(self.client.get(self.url("posts")).json()["pagination"]["total"], 7)
        for value in Post.Category.values:
            data = self.client.get(self.url("posts"), {"category": value}).json()
            self.assertEqual(data["pagination"]["total"], 1)
            self.assertEqual(data["posts"][0]["category"], value)

    def test_search_title_body_and_current_category(self):
        self.make_post(category="project", title="포트폴리오 피드백", body="서비스 소개")
        self.make_post(category="career", title="이력서", body="포트폴리오 정리")
        self.make_post(category="it", title="다른 글")
        self.assertEqual(self.client.get(self.url("posts"), {"q": "포트폴리오"}).json()["pagination"]["total"], 2)
        self.assertEqual(self.client.get(self.url("posts"), {"q": "포트폴리오", "category": "career"}).json()["pagination"]["total"], 1)

    def test_newest_first_and_paginated(self):
        ids = [self.make_post(title=str(i)).pk for i in range(25)]
        first = self.client.get(self.url("posts")).json()
        self.assertEqual(len(first["posts"]), 12)
        self.assertEqual(first["posts"][0]["id"], ids[-1])
        self.assertEqual(first["pagination"]["pages"], 3)
        last = self.client.get(self.url("posts"), {"page": "100000"}).json()
        self.assertEqual(last["pagination"]["page"], 3)
        self.assertEqual(len(last["posts"]), 1)

    def test_empty_list_has_valid_pagination(self):
        result = self.client.get(self.url("posts")).json()
        self.assertEqual(result, {"posts": [], "pagination": {"page": 1, "pages": 1, "total": 0}})

    def test_invalid_filters_and_page_numbers(self):
        for params in [{"category": "fake"}, {"page": "-1"}, {"page": "abc"}, {"page": "0"}, {"q": "a" * 101}]:
            self.assertEqual(self.client.get(self.url("posts"), params).status_code, 400)

    def test_blank_long_and_unknown_post_fields_are_rejected(self):
        valid = {"category": "free", "title": "테스트", "body": "본문"}
        for change in [{"title": "  "}, {"body": "\n "}, {"title": "a" * 141}, {"body": "a" * 20001}, {"category": "unknown"}, {"body": []}, {"title": True}]:
            self.assertEqual(self.send("post", self.url("posts"), {**valid, **change}).status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_invalid_json_and_oversized_requests(self):
        url = self.url("posts")
        for raw in ["{", "[]", "null", '"value"']:
            self.assertEqual(self.client.post(url, raw, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, "a" * 100001, content_type="application/json").status_code, 413)
        self.assertEqual(self.client.post(url, {"title": "x"}).status_code, 415)

    def test_only_staff_can_create_notices(self):
        data = {"category": "notice", "title": "공지사항", "body": "운영 공지"}
        self.assertEqual(self.send("post", self.url("posts"), data).status_code, 403)
        self.assertEqual(self.send("post", self.url("posts"), data, self.staff).status_code, 201)

    def test_author_can_edit_own_post_with_version(self):
        item = self.make_post()
        result = self.send("patch", self.url("post-detail", item.pk), {"title": "수정 제목", "category": "study", "version": item.updated_at.isoformat()})
        self.assertEqual(result.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.title, "수정 제목")
        self.assertEqual(item.category, "study")
        self.assertEqual(item.body, "첫 번째 줄\n코드: print('hello')")

    def test_stale_post_edits_do_not_overwrite_new_changes(self):
        item = self.make_post()
        old = item.updated_at.isoformat()
        url = self.url("post-detail", item.pk)
        self.assertEqual(self.send("patch", url, {"title": "최신 제목", "version": old}).status_code, 200)
        self.assertEqual(self.send("patch", url, {"title": "오래된 제목", "version": old}).status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.title, "최신 제목")

    def test_other_users_cannot_edit_or_delete_post(self):
        item = self.make_post()
        url = self.url("post-detail", item.pk)
        visible = self.other.get(url).json()["post"]
        self.assertFalse(visible["canEdit"])
        self.assertFalse(visible["canDelete"])
        self.assertEqual(self.send("patch", url, {"title": "바꿔치기", "version": item.updated_at.isoformat()}, self.other).status_code, 403)
        self.assertEqual(self.send("delete", url, client=self.other).status_code, 403)

    def test_admin_can_moderate_posts_without_changing_author(self):
        item = self.make_post()
        url = self.url("post-detail", item.pk)
        self.assertEqual(self.send("patch", url, {"title": "관리자 수정", "version": item.updated_at.isoformat()}, self.staff).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.author, self.author)
        self.assertEqual(self.send("delete", url, client=self.staff).status_code, 200)
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        self.assertEqual(item.revision, 3)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_normal_user_cannot_move_post_to_notices(self):
        item = self.make_post()
        self.assertEqual(self.send("patch", self.url("post-detail", item.pk), {"category": "notice", "version": item.updated_at.isoformat()}).status_code, 403)

    def test_removed_staff_role_cannot_edit_existing_notice(self):
        item = self.make_post(author=self.author, category="notice")
        self.assertFalse(self.client.get(self.url("post-detail", item.pk)).json()["post"]["canEdit"])
        self.assertEqual(self.send("patch", self.url("post-detail", item.pk), {"category": "free", "version": item.updated_at.isoformat()}).status_code, 403)

    def test_deleting_post_preserves_records_but_hides_post_and_comments(self):
        item = self.make_post()
        Comment.objects.create(post=item, author=self.reader, body="답변")
        self.assertEqual(self.send("delete", self.url("post-detail", item.pk)).status_code, 200)
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        self.assertTrue(Comment.objects.filter(post=item).exists())
        self.assertEqual(self.client.get(self.url("post-detail", item.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url("comments", item.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url("posts")).json()["posts"], [])

    def test_comments_use_authenticated_author_and_update_counts(self):
        item = self.make_post()
        result = self.send("post", self.url("comments", item.pk), {"body": "코드 피드백\nhttps://example.com", "author_id": self.author.pk}, self.other)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["comment"]["author"]["id"], self.reader.pk)
        self.assertEqual(self.client.get(self.url("post-detail", item.pk)).json()["post"]["commentCount"], 1)
        self.assertEqual(self.client.get(self.url("posts")).json()["posts"][0]["commentCount"], 1)

    def test_comments_can_be_read_in_order_and_paginated(self):
        item = self.make_post()
        for i in range(31):
            Comment.objects.create(post=item, author=self.author, body=str(i))
        result = self.client.get(self.url("comments", item.pk)).json()
        self.assertEqual(len(result["comments"]), 30)
        self.assertEqual(result["comments"][0]["body"], "0")
        last = self.client.get(self.url("comments", item.pk), {"page": "100000"}).json()
        self.assertEqual(last["comments"][0]["body"], "30")

    def test_blank_and_long_comments_rejected(self):
        item = self.make_post()
        for body in [" ", "a" * 2001, []]:
            self.assertEqual(self.send("post", self.url("comments", item.pk), {"body": body}).status_code, 400)
        self.assertFalse(Comment.objects.exists())

    def test_own_comment_can_be_edited_and_deleted(self):
        item = self.make_post()
        comment = Comment.objects.create(post=item, author=self.author, body="원래 댓글")
        url = self.url("comment-detail", comment.pk)
        result = self.send("patch", url, {"body": "수정 댓글", "version": comment.updated_at.isoformat()})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["comment"]["body"], "수정 댓글")
        self.assertEqual(self.send("delete", url).status_code, 200)

    def test_stale_comment_changes_are_rejected(self):
        item = self.make_post()
        comment = Comment.objects.create(post=item, author=self.author, body="원래 댓글")
        old = comment.updated_at.isoformat()
        url = self.url("comment-detail", comment.pk)
        self.assertEqual(self.send("patch", url, {"body": "새 댓글", "version": old}).status_code, 200)
        self.assertEqual(self.send("patch", url, {"body": "덮어쓰기", "version": old}).status_code, 409)

    def test_other_users_cannot_edit_or_delete_comment(self):
        item = self.make_post()
        comment = Comment.objects.create(post=item, author=self.author, body="댓글")
        url = self.url("comment-detail", comment.pk)
        self.assertEqual(self.send("patch", url, {"body": "바꾸기", "version": comment.updated_at.isoformat()}, self.other).status_code, 403)
        self.assertEqual(self.send("delete", url, client=self.other).status_code, 403)

    def test_admin_can_moderate_comments(self):
        item = self.make_post()
        comment = Comment.objects.create(post=item, author=self.author, body="댓글")
        url = self.url("comment-detail", comment.pk)
        self.assertEqual(self.send("patch", url, {"body": "관리자 수정", "version": comment.updated_at.isoformat()}, self.staff).status_code, 200)
        self.assertEqual(self.send("delete", url, client=self.staff).status_code, 200)

    def test_deleted_posts_and_comments_return_not_found(self):
        for method, url, body in [("get", self.url("post-detail", 9999), None), ("get", self.url("comments", 9999), None), ("post", self.url("comments", 9999), {"body": "댓글"}), ("delete", self.url("comment-detail", 9999), None)]:
            result = self.client.get(url) if method == "get" else self.send(method, url, body)
            self.assertEqual(result.status_code, 404)

    def test_write_requests_are_csrf_protected(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.author)
        data = {"category": "free", "title": "CSRF 확인", "body": "본문"}
        self.assertEqual(self.send("post", self.url("posts"), data, csrf).status_code, 403)
        csrf.get(reverse("campus:map"))
        token = csrf.cookies[settings.CSRF_COOKIE_NAME].value
        response = csrf.post(self.url("posts"), json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        item = response.json()["post"]
        self.assertEqual(self.send("patch", self.url("post-detail", item["id"]), {"title": "변경", "version": item["updatedAt"]}, csrf).status_code, 403)
        self.assertEqual(self.send("delete", self.url("post-detail", item["id"]), client=csrf).status_code, 403)

    def test_nickname_change_is_reflected_in_posts_and_comments(self):
        item = self.make_post()
        Comment.objects.create(post=item, author=self.author, body="댓글")
        Profile.objects.filter(user=self.author).update(nickname="새 닉네임")
        self.assertEqual(self.client.get(self.url("post-detail", item.pk)).json()["post"]["author"]["nickname"], "새 닉네임")
        self.assertEqual(self.client.get(self.url("comments", item.pk)).json()["comments"][0]["author"]["nickname"], "새 닉네임")

    def test_unsupported_methods_have_json_errors(self):
        response = self.send("delete", self.url("posts"))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET, POST")
