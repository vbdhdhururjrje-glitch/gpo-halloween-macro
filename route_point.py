from dataclasses import asdict, dataclass

@dataclass
class RoutePoint:
    id: int
    type: str
    timestamp: float
    action_index: int

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=int(data["id"]),
            type=str(data["type"]).upper(),
            timestamp=float(data["timestamp"]),
            action_index=int(data["action_index"]),
        )