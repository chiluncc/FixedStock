import orjson
import json
import yaml
import threading
import jsonlines
from typing import Any, Iterable
from pathlib import Path
import logging


def _standard_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        return path
    return Path(path)


def txt_load(path: str | Path) -> str:
    path = _standard_path(path)
    load_data = path.read_text(encoding="utf-8")
    return load_data


def txt_save(data: str, path: str | Path) -> None:
    path = _standard_path(path)
    path.write_text(data, encoding="utf-8")


def json_load(path: str | Path) -> Any:
    path = _standard_path(path)
    load_data = orjson.loads(path.read_bytes())
    return load_data


def json_save(data: Any, path: str | Path) -> None:
    path = _standard_path(path)
    dump_data = orjson.dumps(data, option=orjson.OPT_INDENT_2)
    path.write_bytes(dump_data)


def json_safe_load(path: str | Path) -> Any:
    path = _standard_path(path)
    with open(path, "rb") as f:
        load_data = json.load(f)
    return load_data


def json_safe_save(data: Any, path: str | Path) -> None:
    path = _standard_path(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def json_loads(s: str) -> Any:
    return json.loads(s)


def json_saves(data: Any, *, indent: int=None) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def yaml_load(path: str | Path) -> Any:
    path = _standard_path(path)
    load_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return load_data


def jsonl_load(path: str | Path) -> Any:
    path = _standard_path(path)
    with jsonlines.open(path, "r") as f:
        load_data = [i for i in f]
    return load_data


def jsonl_save(data: Iterable[Any], path: str | Path) -> None:
    path = _standard_path(path)
    with jsonlines.open(path, "w") as f:
        f.write_all(data)


_llm_keys_read_lock = threading.Lock()
_llm_keys: dict[str, str] = None
def keys_llm_load() -> dict[str, str]:
    global _llm_keys
    with _llm_keys_read_lock:
        if _llm_keys is None:
            _llm_keys = yaml_load(Path(".keys/llm.yaml"))
        return _llm_keys


_loggers: dict[str, logging.Logger] = {}
_loggers_lock = threading.Lock()
def get_logger(path: str | Path, *, level: int=logging.DEBUG) -> logging.Logger:
    path = _standard_path(path)
    key = str(path.resolve())
    with _loggers_lock:
        if key in _loggers:
            return _loggers[key]

        logger = logging.getLogger(key)
        logger.setLevel(level)
        logger.propagate = False

        handler = logging.FileHandler(path, mode="w", encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

        _loggers[key] = logger
        return logger


_null_logger: logging.Logger | None = None
_null_logger_lock = threading.Lock()
def get_default_logger(logger: logging.Logger | None) -> logging.Logger:
    global _null_logger
    if logger is not None:
        return logger
    with _null_logger_lock:
        if _null_logger is None:
            _null_logger = logging.getLogger("null")
            _null_logger.addHandler(logging.NullHandler())
        return _null_logger