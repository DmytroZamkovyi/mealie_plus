"""Constants for Shopping Sync."""

from __future__ import annotations

DOMAIN = "shopping_sync"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_PREFIX = "prefix"
CONF_INTERVAL = "interval"
CONF_PURGE_DAYS = "purge_days"
CONF_PROPAGATE_DELETES = "propagate_deletes"
CONF_WEBHOOK_ID = "webhook_id"

DEFAULT_PREFIX = "Mealie: "
DEFAULT_INTERVAL = 5  # minutes
DEFAULT_PURGE_DAYS = 7
DEFAULT_PROPAGATE_DELETES = True

STORE_VERSION = 1
ISSUE_AMBIGUOUS = "ambiguous_food"
