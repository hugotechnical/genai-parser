import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional


class InfoFilter(logging.Filter):
    """Chỉ cho phép log level INFO"""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.INFO


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Setup logger dùng chung cho toàn app

    - Console: INFO+
    - info.log: chỉ INFO
    - error.log: ERROR+
    """

    logger_name = name or __name__
    logger = logging.getLogger(logger_name)

    # Tránh add handler nhiều lần
    if logger.handlers:
        return logger

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(filename)s:%(lineno)d",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ===== Console handler =====
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # ===== ERROR file handler =====
    error_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "error.log"),
        maxBytes=1000000,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # ===== INFO file handler =====
    info_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "info.log"),
        maxBytes=1000000,
        backupCount=5,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(InfoFilter())
    info_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(error_handler)
    logger.addHandler(info_handler)

    # Không propagate lên root (tránh log trùng)
    logger.propagate = False

    return logger
