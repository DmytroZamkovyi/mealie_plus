"""Runs the sync: one group per Mealie list, targets found by name."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_INTERVAL,
    CONF_PREFIX,
    CONF_PROPAGATE_DELETES,
    CONF_PURGE_DAYS,
    DEFAULT_INTERVAL,
    DEFAULT_PREFIX,
    DEFAULT_PROPAGATE_DELETES,
    DEFAULT_PURGE_DAYS,
    DOMAIN,
    ISSUE_AMBIGUOUS,
    STORE_VERSION,
)
from .core.foods import FoodIndex
from .core.group import GroupState, TargetPlatform, sync_group
from .core.models import Config, SrcNew
from .core.tables import default_tables
from .core.units import UNIT_BY_NAME, norm, unit_key
from .ha_todo import TodoTarget
from .mealie import MealieAuthError, MealieClient, MealieError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ListSource:
    """One Mealie list as the source of a group."""

    def __init__(self, client: MealieClient, list_id: str) -> None:
        self._client = client
        self._list_id = list_id

    async def items(self):
        return (await self._client.items()).get(self._list_id, [])

    async def create(self, items: list[SrcNew]) -> dict[str, str]:
        out: dict[str, str] = {}
        for n in items:
            try:
                out[n.tmp] = await self._client.create_item(n)
            except MealieError as err:
                _LOGGER.warning("Creating an item in Mealie failed: %s", err)
        return out

    async def set_checked(self, ids: list[str], checked: bool) -> None:
        await self._client.set_checked(ids, checked)

    async def delete(self, ids: list[str]) -> None:
        await self._client.delete(ids)


@dataclass
class ShoppingSyncData:
    coordinator: "SyncCoordinator"
    external: dict[str, dict[str, TargetPlatform]] = field(default_factory=dict)  # norm list name -> id -> target


class SyncCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: "ConfigEntry"

    def __init__(self, hass: HomeAssistant, entry: "ConfigEntry", client: MealieClient) -> None:
        opts = entry.options
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=int(opts.get(CONF_INTERVAL, DEFAULT_INTERVAL))),
        )
        self.client = client
        self.external: dict[str, dict[str, TargetPlatform]] = {}
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._states: dict[str, GroupState] = {}
        self._aliases: dict[str, str] = {}  # typed text -> Mealie food id, confirmed in Repairs
        self._unsub_watch = None

    # --- storage
    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._states = {k: GroupState.from_json(v) for k, v in (raw.get("groups") or {}).items()}
        self._aliases = dict(raw.get("aliases") or {})

    async def _save(self) -> None:
        await self._store.async_save(
            {"groups": {k: v.to_json() for k, v in self._states.items()}, "aliases": self._aliases}
        )

    async def async_remove_store(self) -> None:
        await self._store.async_remove()

    async def async_add_alias(self, text: str, food_id: str) -> None:
        self._aliases[norm(text)] = food_id
        await self._save()
        await self.async_request_refresh()

    # --- discovery
    def _prefix(self) -> str:
        return self.config_entry.options.get(CONF_PREFIX, DEFAULT_PREFIX)

    def _find_targets(self, list_name: str) -> dict[str, TargetPlatform]:
        """Todo entities named '<prefix><list name>' plus externally registered targets."""
        wanted = norm(self._prefix() + list_name)
        found: dict[str, TargetPlatform] = {}
        for state in self.hass.states.async_all("todo"):
            if norm(state.attributes.get("friendly_name", "")) == wanted:
                found[state.entity_id] = TodoTarget(self.hass, state.entity_id)
        for tid, target in self.external.get(norm(list_name), {}).items():
            found[f"external:{tid}"] = target
        return found

    # --- cycle
    async def _async_update_data(self) -> dict[str, Any]:
        opts = self.config_entry.options
        try:
            lists = await self.client.lists()
            foods = await self.client.foods()
            units = await self.client.units()
        except MealieAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise UpdateFailed("Mealie rejected the token") from err
        except MealieError as err:
            raise UpdateFailed(str(err)) from err

        unit_aliases: dict[str, str] = {}
        for u in units:
            if u["name"] not in UNIT_BY_NAME:
                continue
            for text in (u.get("pluralName"), u.get("abbreviation"), u.get("pluralAbbreviation"),
                         *[a.get("name") for a in u.get("aliases") or []]):
                if text:
                    unit_aliases.setdefault(unit_key(text), u["name"])
        tables = default_tables(FoodIndex(foods, self._aliases), extra_unit_aliases=unit_aliases)

        summary: dict[str, Any] = {}
        watched: set[str] = set()
        now = dt_util.utcnow()
        for lst in lists:
            targets = self._find_targets(lst["name"])
            if not targets:
                continue
            watched |= {t for t in targets if not t.startswith("external:")}
            cfg = Config(
                inbox_list_id=lst["id"],
                propagate_deletes=bool(opts.get(CONF_PROPAGATE_DELETES, DEFAULT_PROPAGATE_DELETES)),
                purge_days=int(opts.get(CONF_PURGE_DAYS, DEFAULT_PURGE_DAYS)),
            )
            try:
                result = await sync_group(
                    ListSource(self.client, lst["id"]),
                    targets,
                    self._states.get(lst["id"], GroupState()),
                    cfg,
                    tables,
                    now,
                )
            except MealieAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                raise UpdateFailed("Mealie rejected the token") from err
            except MealieError as err:
                raise UpdateFailed(str(err)) from err
            self._states[lst["id"]] = result.state
            for err in result.errors:
                _LOGGER.warning("%s: %s", lst["name"], err)
            self._raise_issues(result.issues)
            summary[lst["name"]] = {
                "targets": sorted(targets),
                "skipped": result.skipped,
                "errors": len(result.errors),
                "purged": result.purged,
            }
        # forget state of lists that no longer exist
        self._states = {k: v for k, v in self._states.items() if k in {l["id"] for l in lists}}
        await self._save()
        self._watch(watched)
        return summary

    # --- instant reaction to changes made in Home Assistant
    @callback
    def _watch(self, entity_ids: set[str]) -> None:
        if self._unsub_watch:
            self._unsub_watch()
            self._unsub_watch = None
        if entity_ids:
            self._unsub_watch = async_track_state_change_event(
                self.hass, sorted(entity_ids), lambda _event: self.hass.async_create_task(self.async_request_refresh())
            )

    @callback
    def async_stop_watching(self) -> None:
        if self._unsub_watch:
            self._unsub_watch()
            self._unsub_watch = None

    # --- repairs
    def _raise_issues(self, issues) -> None:
        for issue in issues:
            if issue.kind != "ambiguous_food":
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_AMBIGUOUS}_{self.config_entry.entry_id}_{norm(issue.text)}",
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_AMBIGUOUS,
                translation_placeholders={"text": issue.text},
                data={
                    "entry_id": self.config_entry.entry_id,
                    "text": issue.text,
                    "candidates": {c.id: c.name for c in issue.candidates},
                },
            )
