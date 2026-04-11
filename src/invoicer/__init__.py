"""r001-05-invoicer — Clockify → Qonto invoicing CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("r001-05-invoicer")
except PackageNotFoundError:
    # Source checkout without an installed distribution — fall back to a
    # sentinel so `invoicer help` still renders instead of crashing.
    __version__ = "0+unknown"
