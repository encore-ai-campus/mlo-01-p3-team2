"""Catalog codes and UUIDv4 identities issued once for the prototype catalog."""
from uuid import UUID

CATALOG_IDS = {
    ("class-group", "mlo-1"): UUID("11447094-0d6e-4a23-af95-046197f09176"),
    ("class-group", "mlo-2"): UUID("f6ca7b43-bc09-4c82-a7e4-f1a48bdc21f3"),
    ("class-group", "mlo-3"): UUID("2cc41077-6fe6-402f-8be4-9e6a534059ca"),
    ("class-group", "skn-34"): UUID("fa054023-6ca8-46a7-9d49-87ac49be7cc6"),
    ("class-group", "skn-36"): UUID("03fb0fa9-26a1-4865-b434-0aaebc83b5c8"),
    ("class-group", "aio-4"): UUID("c25cbb3b-c4df-4234-a0e6-f1385ea7fb94"),
    ("class-group", "unassigned"): UUID("31a2cc4c-ddd8-4c6a-bcd0-846dbe774f32"),
    ("floor", "campus"): UUID("e389216d-067b-4716-aebd-43173921983a"),
    ("floor", "rooftop"): UUID("b4845343-2701-481f-8cb3-1ce4290fea3f"),
    ("zone", "class34-board"): UUID("3726e06f-bebc-47b1-a647-0a955beddcd6"),
    ("zone", "psych-booth"): UUID("909faffa-23de-4fda-9c26-5b46c8a8e783"),
    ("zone", "game-booth"): UUID("0ad110a0-1fcf-42fd-b093-18b938e92ab0"),
    ("zone", "python-classroom"): UUID("2f1c4e63-42e8-4672-952f-732f29f28738"),
    ("zone", "sql-classroom"): UUID("eeffc103-cde9-4048-9dd5-7e8c05b8f4d8"),
    ("category", "game"): UUID("4162b8c2-cd2a-4274-b8a6-b08474b16a33"),
    ("category", "psychology"): UUID("f67b0df1-c073-4455-9f98-005bf6882f55"),
    ("category", "python"): UUID("51c344fd-28f8-42f8-b618-619d41954fdb"),
    ("category", "sql"): UUID("773a96e6-419e-484f-9566-edc65fdb87af"),
    ("content", "gomoku"): UUID("911510a3-5f0d-42f5-b5ec-3ed0ac4bfebe"),
    ("content", "war"): UUID("a68383ec-8dd0-4357-9503-be68e525e886"),
    ("content", "dad-and-me"): UUID("b6c5ea3c-cd02-4537-b764-9a2b3bc0e325"),
    ("content", "minesweeper"): UUID("26fa843f-7b89-46ed-9d6d-ff9aecf2cca2"),
    ("content", "fruit-box"): UUID("6151bdea-7ee1-4009-b01b-400e585c2a53"),
    ("content", "bubble-shooter"): UUID("e03b368a-2daf-48d3-b6ee-f456ec416763"),
    ("content", "suika"): UUID("c03bb858-4962-460a-93e2-4e70d4db0485"),
    ("content", "flashman"): UUID("c44c5181-3756-4871-8f65-3f6a849e0075"),
    ("content", "tetris"): UUID("44a6195f-898f-4200-98e0-380749e1985c"),
    ("content", "worlds-hardest-game"): UUID("11a19b7a-adee-48a0-b5f1-89b3de8fda6d"),
    ("content", "bamboo-master"): UUID("95535f67-fc1f-43cc-8d25-557ca4afbce1"),
    ("content", "sword-upgrade"): UUID("4e69fdc3-7004-43ff-a4b8-38c58867d8fe"),
    ("content", "walk-the-stork"): UUID("93d9872c-75ce-4669-ba8b-6b6603e19ffe"),
    ("content", "isaac"): UUID("f23c08cd-c9d4-49be-b8ca-a639f60cc080"),
    ("content", "paladog"): UUID("2a473609-51c6-4c90-b899-769767bf0287"),
    ("content", "solitaire"): UUID("daaa0e91-113a-4b88-a1e6-653446aba1b8"),
    ("content", "psych-test"): UUID("f5a32338-1b5a-40d5-a30f-195e7011cf21"),
    ("content", "python-multiple-choice"): UUID("0a2e7beb-e01b-4c0f-b0b6-85dbe00452d6"),
    ("content", "python-fill-blank"): UUID("e2046ecc-2c00-4c72-912c-4dc10479d72e"),
    ("content", "sql-multiple-choice"): UUID("8d2c99bf-eefe-43fd-871e-50122bc417c8"),
    ("content", "sql-fill-blank"): UUID("424c4db5-0a92-42e2-a009-23c675c2b889"),
}


def stable_uuid(kind, code):
    return CATALOG_IDS[(kind, code)]


CLASS_GROUPS = (
    ("mlo-1", "MLO 1기"),
    ("mlo-2", "MLO 2기"),
    ("mlo-3", "MLO 3기"),
    ("skn-34", "SKN 34기"),
    ("skn-36", "SKN 36기"),
    ("aio-4", "AIO 4기"),
    ("unassigned", "미지정"),
)
FLOORS = (
    ("campus", "18층 캠퍼스"),
    ("rooftop", "옥상"),
)
ZONES = (
    ("campus", "class34-board", "CLASSROOM", "3·4 강의실 게시판"),
    ("rooftop", "psych-booth", "CONTENT", "심리 테스트 존"),
    ("rooftop", "game-booth", "CONTENT", "게임 부스"),
    ("campus", "python-classroom", "CLASSROOM", "1 강의실 Python 학습교실"),
    ("campus", "sql-classroom", "CLASSROOM", "2 강의실 SQL 학습교실"),
)
CATEGORIES = (
    ("game", "REST", "게임 콘텐츠"),
    ("psychology", "REST", "심리 테스트"),
    ("python", "LEARNING", "Python 학습"),
    ("sql", "LEARNING", "SQL 학습"),
)
CONTENTS = (
    ("gomoku", "game", "오목", "EXTERNAL_LINK", "https://vidkidz.tistory.com/192#waflashContainer", "game-booth"),
    ("war", "game", "전쟁시대", "EXTERNAL_LINK", "https://vidkidz.tistory.com/51#waflashContainer", "game-booth"),
    ("dad-and-me", "game", "아빠와 나", "EXTERNAL_LINK", "https://vidkidz.tistory.com/605#waflashContainer", "game-booth"),
    ("minesweeper", "game", "지뢰찾기", "EXTERNAL_LINK", "https://minesweeper.one/%EC%A7%80%EB%A2%B0%EC%B0%BE%EA%B8%B0/", "game-booth"),
    ("fruit-box", "game", "사과게임", "EXTERNAL_LINK", "https://www.gamesaien.com/game/fruit_box_a/", "game-booth"),
    ("bubble-shooter", "game", "버블슈터", "EXTERNAL_LINK", "https://vidkidz.tistory.com/1514#waflashContainer", "game-booth"),
    ("suika", "game", "수박게임", "EXTERNAL_LINK", "https://playsuikagame.com/ko", "game-booth"),
    ("flashman", "game", "후레시맨", "EXTERNAL_LINK", "https://vidkidz.tistory.com/54#waflashContainer", "game-booth"),
    ("tetris", "game", "테트리스", "EXTERNAL_LINK", "https://vidkidz.tistory.com/4015", "game-booth"),
    ("worlds-hardest-game", "game", "세상에서 가장 어려운 게임", "EXTERNAL_LINK", "https://vidkidz.tistory.com/12", "game-booth"),
    ("bamboo-master", "game", "죽림고수", "EXTERNAL_LINK", "https://vidkidz.tistory.com/107", "game-booth"),
    ("sword-upgrade", "game", "검 강화하기", "EXTERNAL_LINK", "https://vidkidz.tistory.com/5291", "game-booth"),
    ("walk-the-stork", "game", "황새와 오래 걷기", "EXTERNAL_LINK", "https://vidkidz.tistory.com/2825", "game-booth"),
    ("isaac", "game", "아이작", "EXTERNAL_LINK", "https://vidkidz.tistory.com/6014", "game-booth"),
    ("paladog", "game", "팔라독", "EXTERNAL_LINK", "https://vidkidz.tistory.com/5298", "game-booth"),
    ("solitaire", "game", "솔리테어", "EXTERNAL_LINK", "https://thesolitaire.com/ko", "game-booth"),
    ("psych-test", "psychology", "심심테스트", "EXTERNAL_LINK", "https://simsimtest.com/", "psych-booth"),
    ("python-multiple-choice", "python", "Python 객관식", "QUIZ", None, "python-classroom"),
    ("python-fill-blank", "python", "Python 코드 빈칸", "QUIZ", None, "python-classroom"),
    ("sql-multiple-choice", "sql", "SQL 객관식", "QUIZ", None, "sql-classroom"),
    ("sql-fill-blank", "sql", "SQL 코드 빈칸", "QUIZ", None, "sql-classroom"),
)


def class_group_uuid(cohort):
    code = cohort if cohort in {item[0] for item in CLASS_GROUPS[:-1]} else "unassigned"
    return stable_uuid("class-group", code)


def floor_uuid(code):
    return stable_uuid("floor", code)


def zone_uuid(code):
    return stable_uuid("zone", code)
