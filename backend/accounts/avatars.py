"""The four outfits supported by the campus sprite sheets."""

DEFAULT_AVATAR = "male-1"
AVATARS = (
    {"id": "male-1", "gender": "male", "type": "타입 1", "name": "민트 후드", "description": "민트 후드 · 네이비 팬츠"},
    {"id": "male-2", "gender": "male", "type": "타입 2", "name": "보라색 재킷", "description": "안경 · 보라색 야구 재킷"},
    {"id": "female-1", "gender": "female", "type": "타입 1", "name": "보라색 후드", "description": "보라색 후드 · 데님 팬츠"},
    {"id": "female-2", "gender": "female", "type": "타입 2", "name": "초록색 카디건", "description": "포니테일 · 초록색 카디건"},
)
AVATAR_CHOICES = tuple((avatar["id"], avatar["name"]) for avatar in AVATARS)
AVATAR_IDS = frozenset(avatar["id"] for avatar in AVATARS)


def avatar_options(ids=AVATAR_IDS):
    return [
        {**avatar, "gender_label": "남자" if avatar["gender"] == "male" else "여자",
         "preview": f"campus/assets/characters/{avatar['id']}-preview.png"}
        for avatar in AVATARS if avatar["id"] in ids
    ]
