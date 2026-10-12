"""billing 이 밖으로 내보내는 값 객체(설계 R2)."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class WalletView:
    owner_id: uuid.UUID
    balance: int
    spent_today: int
    budget_day: date
    resets_at: datetime


@dataclass(frozen=True)
class LedgerEntryView:
    entry_id: uuid.UUID
    entry_type: str
    amount: int
    balance_after: int
    campaign_id: uuid.UUID | None
    charge_policy: str
    shortfall: int
    note: str
    created_at: datetime


@dataclass(frozen=True)
class ChargeResult:
    entry: LedgerEntryView
    charged: int  # 실제로 차감한 금액(남은 잔액까지만)
    shortfall: int  # 모자라서 못 받은 금액
    duplicate: bool  # 같은 reaction_ref 의 재호출이라 처음 결과를 그대로 돌려줌
