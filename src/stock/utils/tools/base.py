from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolResult:
    error: bool = field(default=False)
    error_str: str = field(default_factory=str)
    error_trace: str = field(default_factory=str)
    result: str = field(default_factory=str)