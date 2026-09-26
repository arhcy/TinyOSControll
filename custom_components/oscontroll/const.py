"""Constants for the OSControll integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "oscontroll"

CONF_URL: Final = "url"
CONF_TOKEN: Final = "token"
CONF_VERIFY_SSL: Final = "verify_ssl"

DEFAULT_VERIFY_SSL: Final = True

HUB_ID: Final = "hub"

SCAN_INTERVAL_SECONDS: Final = 10

CONTAINER_ACTIONS: Final = ("start", "stop", "restart")
