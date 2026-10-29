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

# AI enrichment (optional, off by default)
CONF_AI_ENABLED = "ai_enabled"
CONF_AI_ENTITY = "ai_entity"
CONF_AI_IMAGE_ENTITY = "ai_image_entity"
CONF_AI_INTERVAL = "ai_interval"  # hours
CONF_AI_LIMIT = "ai_limit"  # objects per run
CONF_AI_IMAGE_LIMIT = "ai_image_limit"  # generated images per run
CONF_AI_LABELS = "ai_labels"
CONF_AI_ALIASES = "ai_aliases"
CONF_AI_UNITS = "ai_units"
CONF_AI_DESCRIPTIONS = "ai_descriptions"
CONF_AI_NUTRITION = "ai_nutrition"
CONF_AI_TOOLS = "ai_tools"
CONF_AI_IMAGES = "ai_images"

DEFAULT_AI_INTERVAL = 24
DEFAULT_AI_LIMIT = 20
DEFAULT_AI_IMAGE_LIMIT = 3
AI_RETRY_DAYS = 14
