"""Mealie Plus: one shared shopping list across Mealie and Home Assistant."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from datetime import timedelta

from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_AI_ENABLED,
    CONF_AI_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_WEBHOOK_ID,
    DEFAULT_AI_INTERVAL,
    DOMAIN,
)
from .coordinator import MealiePlusData, SyncCoordinator
from .core.group import TargetPlatform
from .core.units import norm
from .enrich import Enricher
from .mealie import MealieClient

PLATFORMS = [Platform.BUTTON]

type MealiePlusConfigEntry = ConfigEntry[MealiePlusData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _sync_now(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.coordinator.async_request_refresh()

    async def _enrich_now(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.enricher.async_run()

    hass.services.async_register(DOMAIN, "sync_now", _sync_now)
    hass.services.async_register(DOMAIN, "enrich_now", _enrich_now)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MealiePlusConfigEntry) -> bool:
    client = MealieClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN])
    coordinator = SyncCoordinator(hass, entry, client)
    await coordinator.async_load()
    enricher = Enricher(hass, entry, client)
    await enricher.async_load()
    entry.runtime_data = MealiePlusData(coordinator=coordinator, enricher=enricher)
    coordinator.external = entry.runtime_data.external
    coordinator.async_start_discovery()

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

    webhook.async_register(hass, DOMAIN, "Mealie Plus", webhook_id, _handle, allowed_methods=["POST"])

    if entry.options.get(CONF_AI_ENABLED):
        interval = timedelta(hours=int(entry.options.get(CONF_AI_INTERVAL, DEFAULT_AI_INTERVAL)))

        async def _scheduled(_now) -> None:
            await enricher.async_run()

        entry.async_on_unload(async_track_time_interval(hass, _scheduled, interval))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN} first sync")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MealiePlusConfigEntry) -> bool:
    entry.runtime_data.coordinator.async_stop_watching()
    if webhook_id := entry.data.get(CONF_WEBHOOK_ID):
        webhook.async_unregister(hass, webhook_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MealiePlusConfigEntry) -> None:
    from homeassistant.helpers.storage import Store

    from .const import STORE_VERSION

    await Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
    await Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.enrich").async_remove()


async def _async_reload(hass: HomeAssistant, entry: MealiePlusConfigEntry) -> None:
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
