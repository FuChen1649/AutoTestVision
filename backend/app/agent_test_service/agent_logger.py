"""Agent 服务文件日志：写入 backend/logs/agent_service_<时间戳>.log"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

_LOGGER: logging.Logger | None = None
_LOG_FILE: Path | None = None


def init_agent_logger() -> logging.Logger:
    global _LOGGER, _LOG_FILE
    if _LOGGER is not None:
        return _LOGGER

    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _LOG_FILE = log_dir / f"agent_service_{timestamp}.log"

    logger = logging.getLogger("agent_service")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(console_handler)

    _LOGGER = logger
    logger.info("日志文件已创建: %s", _LOG_FILE)
    return logger


def get_agent_logger() -> logging.Logger:
    if _LOGGER is None:
        return init_agent_logger()
    return _LOGGER


def get_log_file() -> Path | None:
    return _LOG_FILE
