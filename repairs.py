"""Repair flow: choose which Mealie food typed text stands for."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class AmbiguousFoodFlow(RepairsFlow):
    def __init__(self, issue_id: str, data: dict) -> None:
        self._issue_id = issue_id
        self._data = data

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        candidates: dict[str, str] = self._data["candidates"]
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._data["entry_id"])
            if entry and getattr(entry, "runtime_data", None):
                await entry.runtime_data.coordinator.async_add_alias(self._data["text"], user_input["food"])
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("food"): vol.In(candidates)}),
            description_placeholders={"text": self._data["text"]},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return AmbiguousFoodFlow(issue_id, data or {})
