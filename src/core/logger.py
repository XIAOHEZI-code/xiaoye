import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(name: str) -> logging.Logger:
    """
    Sets up a configured logger with console and file handlers.
    Logs are saved to the 'work_log' directory.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Avoid adding handlers multiple times if logger is already configured
    if logger.handlers:
        return logger

    # Ensure log directory exists
    log_dir = os.path.join(os.getcwd(), "work_log")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "xiaoye_system.log")

    # Formatter
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File Handler (Rotate at 10MB, keep 5 backups)
    fh = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger
