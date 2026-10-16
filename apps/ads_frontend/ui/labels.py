"""화면 이름표(설계 §6.6 "6-15 분리"). 값(코드)은 백엔드의 선택지와 같다 — **데이터만 둔다**: 백엔드 시험(`case_frontend_labels_match_the_backend_choices`)이
이 파일을 읽어 백엔드의 선택지(masters·campaigns·billing)와 같은지 본다. 프론트는 백엔드 코드를 가져오지 않는다."""

AUDIENCES = {"individual": "개인", "shared": "일괄"}
CAMPAIGN_STATUSES = {"ACTIVE": "집행 중", "PAUSED": "일시 중지", "SUSPENDED": "관리자 중단", "ENDED": "종료"}
ENTRY_TYPES = {"SIGNUP_GRANT": "가입 지급", "CHARGE": "반응 과금", "ADMIN_ADJUST": "관리자 조정", "TOPUP": "충전(예약, C5)"}
REVIEW_STATUSES = {"OPEN": "대기", "RELEASED": "해제됨", "REJECTED": "반려됨", "CLOSED_ENDED": "캠페인 종료로 닫힘"}
