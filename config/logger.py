"""
config/logger.py

Usage:

    from config.logger import log

    log.debug("Only visible when PROD_ENV is False")
    log.info("Only visible when PROD_ENV is False")
    log.warning("Always visible (WARNING+ is never hidden)")

    log.prod.info("Always visible, even when PROD_ENV is True")
    log.prod.error("Always visible")

How it's wired:
  - "app" logger      -> level jumps to WARNING when PROD_ENV=True,
                          so .debug()/.info() calls are silently dropped.
  - "app.prod" logger -> level is pinned at INFO regardless of PROD_ENV,
                          so .info()/.warning()/.error() always emit.
Both channels and their colors are configured once, in settings.LOGGING.
"""

import logging


class _ProdLog:
    def __init__(self) -> None:
        self._logger = logging.getLogger("app.prod")

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)


class _Log:
    def __init__(self) -> None:
        self._logger = logging.getLogger("app")
        self.prod = _ProdLog()

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)


log = _Log()
