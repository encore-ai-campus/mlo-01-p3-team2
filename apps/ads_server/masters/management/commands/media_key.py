from django.core.management.base import BaseCommand, CommandError

from foundation.api import User, errors
from masters import api


class Command(BaseCommand):
    help = "매체 키를 발급·교체·폐기한다. 평문 키는 발급·교체할 때 한 번만 출력된다(저장하지 않는다)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["issue", "rotate", "revoke"])
        parser.add_argument("target", help="issue·rotate 는 매체 ID, revoke 는 키 ID")
        parser.add_argument("--admin", required=True, help="행위자(관리자 아이디). 감사 로그에 남는다")
        parser.add_argument("--label", default="")
        parser.add_argument("--grace-hours", type=int, default=24, help="rotate: 기존 키가 유효한 유예 시간(기본 24시간)")

    def handle(self, *args, **opts):
        try:
            actor = User.objects.get(username=opts["admin"])
        except User.DoesNotExist:
            raise CommandError("관리자를 찾을 수 없다")
        try:
            if opts["action"] == "revoke":
                api.revoke_media_key(actor, opts["target"])
                self.stdout.write("revoked")
                return
            if opts["action"] == "issue":
                issued = api.issue_media_key(actor, opts["target"], label=opts["label"])
            else:
                issued = api.rotate_media_key(actor, opts["target"], grace_seconds=opts["grace_hours"] * 3600, label=opts["label"])
        except errors.ApiError as e:
            raise CommandError(e.detail or e.title)
        self.stdout.write(f"key_id: {issued.key_id}\nkey: {issued.key}\n(이 키는 다시 볼 수 없다. 매체 서버의 비밀 저장소에 넣는다)")
