"""Shopping Sync: one shared shopping list across Mealie and Home Assistant."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_TOKEN, CONF_URL, CONF_WEBHOOK_ID, DOMAIN
from .coordinator import ShoppingSyncData, SyncCoordinator
from .core.group import TargetPlatform
from .core.units import norm
from .mealie import MealieClient

PLATFORMS = [Platform.BUTTON]

type ShoppingSyncConfigEntry = ConfigEntry[ShoppingSyncData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _sync_now(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "sync_now", _sync_now)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ShoppingSyncConfigEntry) -> bool:
    client = MealieClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN])
    coordinator = SyncCoordinator(hass, entry, client)
    await coordinator.async_load()
    entry.runtime_data = ShoppingSyncData(coordinator=coordinator)
    coordinator.external = entry.runtime_data.external

    # Webhook: any POST means "something changed, sync now". Meant for a Mealie notifier
    # (Apprise json://) and for an external platform. The id is generated once, kept in the
    # entry data and shown in the options dialog.
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id:
        webhook_id = webhook.async_generate_id()
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id})

    async def _handle(hass: HomeAssistant, _id: str, request) -> web.Response:
        hass.async_create_task(coordinator.async_request_refresh())
        return web.Response(status=202)

    webhook.async_register(hass, DOMAIN, "Shopping Sync", webhook_id, _handle, allowed_methods=["POST"])

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN} first sync")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShoppingSyncConfigEntry) -> bool:
    entry.runtime_data.coordinator.async_stop_watching()
    if webhook_id := entry.data.get(CONF_WEBHOOK_ID):
        webhook.async_unregister(hass, webhook_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ShoppingSyncConfigEntry) -> None:
    from homeassistant.helpers.storage import Store

    from .const import STORE_VERSION

    await Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_reload(hass: HomeAssistant, entry: ShoppingSyncConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def async_register_external_target(
    hass: HomeAssistant, list_name: str, target_id: str, target: TargetPlatform
) -> None:
    """Attach a target from another platform to the group of a Mealie list.

    `target` implements `items()` (raise when unreachable), `add`, `update`, `remove`
    (see core/group.py). It receives the same merged lines as a to-do list.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        entry.runtime_data.external.setdefault(norm(list_name), {})[target_id] = target
