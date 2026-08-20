from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime


@dataclass(frozen=True)
class Config:
    stocks: dict[str, list[str]]

    local_data_dir: Path = field(default=Path("data"))
    output_dir: Path = field(default=Path("output"))
    time_start: datetime = field(default_factory=datetime.now())
    time_position: int = field(default=20)
    portfolio_power: float = field(default=0.7)
