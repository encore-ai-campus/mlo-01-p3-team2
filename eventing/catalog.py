"""Catalog codes and UUIDv4 identities issued once for the prototype catalog."""
from uuid import UUID

CATALOG_IDS = {
    ("class-group", "mlo-1"): UUID("11447094-0d6e-4a23-af95-046197f09176"),
    ("class-group", "mlo-2"): UUID("f6ca7b43-bc09-4c82-a7e4-f1a48bdc21f3"),
    ("class-group", "mlo-3"): UUID("2cc41077-6fe6-402f-8be4-9e6a534059ca"),
    ("class-group", "skn-34"): UUID("fa054023-6ca8-46a7-9d49-87ac49be7cc6"),
    ("class-group", "skn-36"): UUID("03fb0fa9-26a1-4865-b434-0aaebc83b5c8"),
    ("class-group", "unassigned"): UUID("31a2cc4c-ddd8-4c6a-bcd0-846dbe774f32"),
    ("floor", "campus"): UUID("e389216d-067b-4716-aebd-43173921983a"),
    ("floor", "rooftop"): UUID("b4845343-2701-481f-8cb3-1ce4290fea3f"),
    ("zone", "class34-board"): UUID("3726e06f-bebc-47b1-a647-0a955beddcd6"),
    ("zone", "psych-booth"): UUID("909faffa-23de-4fda-9c26-5b46c8a8e783"),
    ("zone", "game-booth"): UUID("0ad110a0-1fcf-42fd-b093-18b938e92ab0"),
    ("category", "game"): UUID("4162b8c2-cd2a-4274-b8a6-b08474b16a33"),
    ("category", "psychology"): UUID("f67b0df1-c073-4455-9f98-005bf6882f55"),
    ("content", "gomoku"): UUID("911510a3-5f0d-42f5-b5ec-3ed0ac4bfebe"),
    ("content", "war"): UUID("a68383ec-8dd0-4357-9503-be68e525e886"),
    ("content", "dad-and-me"): UUID("b6c5ea3c-cd02-4537-b764-9a2b3bc0e325"),
    ("content", "minesweeper"): UUID("26fa843f-7b89-46ed-9d6d-ff9aecf2cca2"),
    ("content", "psych-test"): UUID("f5a32338-1b5a-40d5-a30f-195e7011cf21"),
}


def stable_uuid(kind, code):
    return CATALOG_IDS[(kind, code)]


CLASS_GROUPS = (
    ("mlo-1", "MLO 1기"),
    ("mlo-2", "MLO 2기"),
    ("mlo-3", "MLO 3기"),
    ("skn-34", "SKN 34기"),
    ("skn-36", "SKN 36기"),
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
)
CATEGORIES = (
    ("game", "REST", "게임 콘텐츠"),
    ("psychology", "REST", "심리 테스트"),
)
CONTENTS = (
    ("gomoku", "game", "오목", "EXTERNAL_LINK", "https://vidkidz.tistory.com/192#waflashContainer", "game-booth"),
    ("war", "game", "전쟁시대", "EXTERNAL_LINK", "https://vidkidz.tistory.com/51#waflashContainer", "game-booth"),
    ("dad-and-me", "game", "아빠와 나", "EXTERNAL_LINK", "https://vidkidz.tistory.com/605#waflashContainer", "game-booth"),
    ("minesweeper", "game", "지뢰찾기", "EXTERNAL_LINK", "https://minesweeper.one/%EC%A7%80%EB%A2%B0%EC%B0%BE%EA%B8%B0/", "game-booth"),
    ("psych-test", "psychology", "심심테스트", "EXTERNAL_LINK", "https://simsimtest.com/", "psych-booth"),
)


def class_group_uuid(cohort):
    code = cohort if cohort in {item[0] for item in CLASS_GROUPS[:-1]} else "unassigned"
    return stable_uuid("class-group", code)


def floor_uuid(code):
    return stable_uuid("floor", code)


def zone_uuid(code):
    return stable_uuid("zone", code)
