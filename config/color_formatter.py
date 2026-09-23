"""
core/color_formatter.py

Custom logging formatters using raw ANSI escape codes, so every log level
gets an exact, intentional color instead of whatever a library's default
palette happens to offer.

Works on macOS/Linux terminals natively. On Windows, colorama.init() (called
below) translates ANSI codes so colors still render in cmd.exe / PowerShell.

If your terminal is very old and doesn't support 256-color ANSI codes, the
orange (38;5;208) may fall back to your terminal's default text color —
everything else uses the safe 16-color codes and will always work.
"""

import logging

try:
    import colorama  # type: ignore[import-untyped]

    colorama.init(autoreset=False)
except ImportError:
    pass  # colorama is only needed on Windows; harmless if missing elsewhere

RESET = "\033[0m"

# Normal "app" channel — log.debug() / log.info() / log.warning() / log.error()
LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[38;5;208m",  # orange
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;37;41m",  # white on red background
}

# "app.prod" channel — log.prod.info() etc. Bold/magenta family so these
# always-on lines are visually distinct from the normal channel above.
PROD_LEVEL_COLORS = {
    logging.DEBUG: "\033[1;36m",  # bold cyan
    logging.INFO: "\033[1;35m",  # bold magenta
    logging.WARNING: "\033[1;33m",  # bold yellow
    logging.ERROR: "\033[1;31m",  # bold red
    logging.CRITICAL: "\033[1;37;41m",  # white on red background
}


class ColorFormatter(logging.Formatter):
    """Wraps the formatted line in an ANSI color based on the record's level."""

    colors = LEVEL_COLORS

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = self.colors.get(record.levelno)
        return f"{color}{message}{RESET}" if color else message


class ProdColorFormatter(ColorFormatter):
    colors = PROD_LEVEL_COLORS
