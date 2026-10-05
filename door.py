from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DoorState(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKING = "CHECKING"
    SUCCESS = "SUCCESS"
    COOLDOWN = "COOLDOWN"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"


@dataclass
class Door:
    id: int
    route_order: int
    timestamp: float
    action_index: int
    state: DoorState = DoorState.AVAILABLE
    cooldown_until: Optional[float] = None
    last_attempt: Optional[float] = None
    last_result: Optional[str] = None
    last_candy_amount: Optional[int] = None
    failed_ocr_count: int = 0