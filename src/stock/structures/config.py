from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime


@dataclass(frozen=True)
class Config:
    local_data_dir: Path
    output_dir: Path
    stocks: dict[str, list[str]]

    time_start: datetime = field(default_factory=datetime.now())
    time_position: int = field(default=20)
