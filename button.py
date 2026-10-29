"""Buttons: sync now, AI enrichment now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_AI_ENABLED, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback) -> None:
    buttons: list[ButtonEntity] = [SyncNowButton(entry)]
    if entry.options.get(CONF_AI_ENABLED):
        buttons.append(EnrichNowButton(entry))
    async_add_entities(buttons)


class _Base(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, key: str) -> None:
        self._entry = entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Shopping Sync")


class SyncNowButton(_Base):
    def __init__(self, entry) -> None:
        super().__init__(entry, "sync_now")

    async def async_press(self) -> None:
        await self._entry.runtime_data.coordinator.async_request_refresh()


class EnrichNowButton(_Base):
    def __init__(self, entry) -> None:
        super().__init__(entry, "enrich_now")

    async def async_press(self) -> None:
        await self._entry.runtime_data.enricher.async_run()
