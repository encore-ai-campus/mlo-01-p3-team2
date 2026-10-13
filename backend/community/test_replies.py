import json
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Profile
from .models import Comment, Post


class ReplyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user(username="reply_author", password="Reply!4820")
        cls.reader = User.objects.create_user(username="reply_reader", password="Reply!4820")
        cls.admin = User.objects.create_user(username="reply_admin", password="Reply!4820", is_staff=True)
        for user, nickname in ((cls.author, "댓글 작성자"), (cls.reader, "답글 작성자"), (cls.admin, "관리자")):
            Profile.objects.create(user=user, nickname=nickname)
        cls.post = Post.objects.create(author=cls.author, category="free", title="답글 테스트", body="본문")
        cls.parent = Comment.objects.create(post=cls.post, author=cls.author, body="원래 댓글")

    def setUp(self):
        self.client.force_login(self.author)
        self.other = Client()
        self.other.force_login(self.reader)
        self.staff = Client()
        self.staff.force_login(self.admin)

    def url(self, name, *args):
        return reverse("community:" + name, args=args)

    def send(self, method, url, data=None, client=None):
        return getattr(client or self.client, method)(
            url, data=json.dumps(data) if data is not None else "", content_type="application/json",
        )

    def reply(self, parent=None, client=None):
        parent = parent or self.parent
        return self.send("post", self.url("comments", self.post.pk), {
            "body": "답글 내용", "parentCommentUuid": str(parent.comment_uuid),
        }, client or self.other)

    def test_reply_is_linked_by_uuid_and_uses_authenticated_author(self):
        response = self.reply()
        self.assertEqual(response.status_code, 201)
        result = response.json()["comment"]
        reply = Comment.objects.get(pk=result["id"])
        self.assertEqual(reply.parent_id, self.parent.comment_uuid)
        self.assertEqual(reply.author, self.reader)
        self.assertEqual(result["parentCommentUuid"], str(self.parent.comment_uuid))
        self.assertFalse(result["canReply"])
        detail = self.client.get(self.url("post-detail", self.post.pk)).json()["post"]
        self.assertEqual(detail["commentCount"], 2)

    def test_plain_comments_keep_a_null_parent(self):
        response = self.send("post", self.url("comments", self.post.pk), {"body": "일반 댓글"})
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["comment"]["parentCommentUuid"])
        self.assertTrue(response.json()["comment"]["canReply"])

    def test_malformed_parent_uuid_is_rejected(self):
        for value in ("", "bad-id", 1, True, [], {}, str(uuid.uuid1())):
            with self.subTest(value=value):
                response = self.send("post", self.url("comments", self.post.pk), {
                    "body": "답글", "parentCommentUuid": value,
                })
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), 1)

    def test_parent_must_exist_be_active_and_belong_to_the_same_post(self):
        another = Post.objects.create(author=self.author, category="free", title="다른 글", body="본문")
        foreign = Comment.objects.create(post=another, author=self.author, body="다른 글 댓글")
        for value in (str(uuid.uuid4()), str(foreign.comment_uuid)):
            response = self.send("post", self.url("comments", self.post.pk), {
                "body": "답글", "parentCommentUuid": value,
            })
            self.assertEqual(response.status_code, 404)
        self.send("delete", self.url("comment-detail", self.parent.pk))
        self.assertEqual(self.reply().status_code, 404)
        self.assertFalse(Comment.objects.filter(parent__isnull=False).exists())

    def test_reply_to_a_reply_is_rejected(self):
        reply = Comment.objects.get(pk=self.reply().json()["comment"]["id"])
        self.assertEqual(self.reply(reply).status_code, 400)
        self.assertEqual(Comment.objects.filter(parent__isnull=False).count(), 1)

    def test_pagination_keeps_whole_threads_and_counts_replies(self):
        roots = [self.parent] + [Comment.objects.create(post=self.post, author=self.author, body=str(i)) for i in range(30)]
        first_reply = Comment.objects.get(pk=self.reply(roots[0]).json()["comment"]["id"])
        last_reply = Comment.objects.get(pk=self.reply(roots[-1]).json()["comment"]["id"])
        first = self.client.get(self.url("comments", self.post.pk)).json()
        self.assertEqual(first["pagination"], {"page": 1, "pages": 2, "total": 31})
        self.assertEqual(first["commentCount"], 33)
        self.assertEqual(len(first["comments"]), 30)
        self.assertEqual(first["comments"][0]["replies"][0]["id"], first_reply.pk)
        last = self.client.get(self.url("comments", self.post.pk), {"page": "2"}).json()
        self.assertEqual([item["id"] for item in last["comments"]], [roots[-1].pk])
        self.assertEqual(last["comments"][0]["replies"][0]["id"], last_reply.pk)

    def test_deleted_parent_is_a_placeholder_and_keeps_live_replies(self):
        result = self.reply().json()["comment"]
        self.assertEqual(self.send("delete", self.url("comment-detail", self.parent.pk)).status_code, 200)
        data = self.client.get(self.url("comments", self.post.pk)).json()
        parent = data["comments"][0]
        self.assertTrue(parent["isDeleted"])
        self.assertEqual(parent["body"], "삭제된 댓글입니다.")
        self.assertIsNone(parent["author"])
        self.assertFalse(parent["canEdit"] or parent["canDelete"] or parent["canReply"])
        self.assertNotIn("원래 댓글", json.dumps(data, ensure_ascii=False))
        self.assertEqual(parent["replies"][0]["id"], result["id"])
        self.assertEqual(data["commentCount"], 1)
        response = self.send("patch", self.url("comment-detail", result["id"]), {
            "body": "부모 삭제 이후 수정", "version": result["updatedAt"],
        }, self.other)
        self.assertEqual(response.status_code, 200)

    def test_placeholder_disappears_when_its_last_reply_is_deleted(self):
        reply = self.reply().json()["comment"]
        self.send("delete", self.url("comment-detail", self.parent.pk))
        self.send("delete", self.url("comment-detail", reply["id"]), client=self.other)
        data = self.client.get(self.url("comments", self.post.pk)).json()
        self.assertEqual(data["comments"], [])
        self.assertEqual(data["commentCount"], 0)
        self.assertEqual(Comment.objects.count(), 2)

    def test_reply_edit_and_delete_permissions_match_comments(self):
        reply = self.reply().json()["comment"]
        url = self.url("comment-detail", reply["id"])
        for method, data in (("patch", {"body": "다른 사람 수정", "version": reply["updatedAt"]}), ("delete", None)):
            self.assertEqual(self.send(method, url, data).status_code, 403)
        updated = self.send("patch", url, {"body": "본인 수정", "version": reply["updatedAt"]}, self.other)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.send("delete", url, client=self.staff).status_code, 200)
        self.assertEqual(self.client.get(self.url("comments", self.post.pk)).json()["comments"][0]["replies"], [])

    def test_reparenting_and_stale_reply_updates_are_rejected(self):
        reply = self.reply().json()["comment"]
        url = self.url("comment-detail", reply["id"])
        self.assertEqual(self.send("patch", url, {
            "body": "부모 변경", "parentCommentUuid": None, "version": reply["updatedAt"],
        }, self.other).status_code, 400)
        self.assertEqual(self.send("patch", url, {
            "body": "새 답글", "version": reply["updatedAt"],
        }, self.other).status_code, 200)
        self.assertEqual(self.send("patch", url, {
            "body": "오래된 수정", "version": reply["updatedAt"],
        }, self.other).status_code, 409)
        stored = Comment.objects.get(pk=reply["id"])
        self.assertEqual((stored.parent_id, stored.body, stored.revision), (self.parent.comment_uuid, "새 답글", 2))

    def test_deleting_post_hides_the_entire_thread_and_rejects_new_replies(self):
        reply = self.reply().json()["comment"]
        self.send("delete", self.url("post-detail", self.post.pk))
        self.assertEqual(self.client.get(self.url("comments", self.post.pk)).status_code, 404)
        self.assertEqual(self.reply().status_code, 404)
        self.assertEqual(self.send("delete", self.url("comment-detail", reply["id"]), client=self.other).status_code, 404)
        self.assertEqual(Comment.objects.count(), 2)
