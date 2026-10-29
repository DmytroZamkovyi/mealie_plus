"""A button that runs the sync right now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SyncNowButton(entry)])


class SyncNowButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync_now"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Shopping Sync")

    async def async_press(self) -> None:
        await self._entry.runtime_data.coordinator.async_request_refresh()
