"""Colourised console logger + per-run rotating file log.

Every module in the framework imports the same singleton:

    from core.logger import logger
    logger.info("hello")

The console handler is colourised (colorlog). A file handler is attached the
first time `start_run_log()` is called, so each test run gets its own file
under logs/ that contains the full DEBUG stream regardless of console level.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import colorlog

LOGGER_NAME = "epbr"
CONSOLE_FORMAT = "%(log_color)s%(asctime)s %(levelname)-8s%(reset)s %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s:%(module)s:%(lineno)d] %(message)s"
DATE_FORMAT = "%H:%M:%S"
FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "white",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red,bg_white",
}


class TesterLogger(logging.Logger):
    """A stdlib Logger with the conveniences the framework relies on."""

    def set_level(self, level: str | int) -> None:
        """Set the *console* level. The file handler always stays at DEBUG."""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        for handler in self.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(level)

    def start_run_log(self, logs_dir: Path, run_name: str) -> Path:
        """Attach a DEBUG file handler for this run and return its path."""
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / f"{timestamp}_{run_name}.log"

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=FILE_DATE_FORMAT))
        self.addHandler(handler)
        self.debug(f"Logging this run to {log_path}")
        return log_path

    def stop_run_log(self) -> None:
        """Detach and close any file handlers (end of a run)."""
        for handler in list(self.handlers):
            if isinstance(handler, logging.FileHandler):
                handler.close()
                self.removeHandler(handler)

    def header(self, text: str, width: int = 60, char: str = "=") -> None:
        """Log a visually separated section header."""
        self.info(char * width)
        self.info(text)
        self.info(char * width)


def _build_logger(name: str = LOGGER_NAME, level: int = logging.INFO) -> TesterLogger:
    logging.setLoggerClass(TesterLogger)
    instance = logging.getLogger(name)
    logging.setLoggerClass(logging.Logger)  # don't affect third-party loggers

    instance.setLevel(logging.DEBUG)  # handlers do the real filtering
    instance.propagate = False

    if not instance.handlers:
        console = colorlog.StreamHandler(stream=sys.stdout)
        console.setLevel(level)
        console.setFormatter(
            colorlog.ColoredFormatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT, log_colors=LOG_COLORS)
        )
        instance.addHandler(console)

    return instance  # type: ignore[return-value]


logger: TesterLogger = _build_logger()


def get_logger(name: Optional[str] = None) -> TesterLogger:
    """Child logger that shares the root handlers (e.g. get_logger("psu"))."""
    if name is None:
        return logger
    return logger.getChild(name)  # type: ignore[return-value]
