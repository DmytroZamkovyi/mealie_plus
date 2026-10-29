"""A Home Assistant `todo` entity as a sync target."""

from __future__ import annotations

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import HomeAssistant

from .core.models import HaItem


class TodoTarget:
    """Implements the engine's target interface on top of the todo services."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        self._hass = hass
        self.entity_id = entity_id

    @property
    def _can_describe(self) -> bool:
        state = self._hass.states.get(self.entity_id)
        features = int(state.attributes.get("supported_features", 0)) if state else 0
        return bool(features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    async def items(self) -> list[HaItem]:
        """Raises when the entity is missing or unavailable: never treated as an empty list."""
        state = self._hass.states.get(self.entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            raise RuntimeError(f"{self.entity_id} is unavailable")
        resp = await self._hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": self.entity_id, "status": ["needs_action", "completed"]},
            blocking=True,
            return_response=True,
        )
        raw = (resp or {}).get(self.entity_id, {}).get("items", [])
        return [
            HaItem(r["uid"], r.get("summary", ""), r.get("description") or "", r.get("status") == "completed")
            for r in raw
        ]

    async def add(self, summary: str, description: str, done: bool) -> str:
        before = {i.uid for i in await self.items()}
        data: dict = {"entity_id": self.entity_id, "item": summary}
        if description and self._can_describe:
            data["description"] = description
        await self._hass.services.async_call("todo", "add_item", data, blocking=True)
        added = [i for i in await self.items() if i.uid not in before]
        if not added:
            raise RuntimeError("added item not found")
        uid = added[-1].uid
        if done:
            await self.update(uid, None, None, True)
        return uid

    async def update(self, uid: str, summary: str | None, description: str | None, done: bool | None) -> None:
        data: dict = {"entity_id": self.entity_id, "item": uid}
        if summary is not None:
            data["rename"] = summary
        if description is not None and self._can_describe:
            data["description"] = description
        if done is not None:
            data["status"] = "completed" if done else "needs_action"
        if len(data) > 2:
            await self._hass.services.async_call("todo", "update_item", data, blocking=True)

    async def remove(self, uid: str) -> None:
        await self._hass.services.async_call(
            "todo", "remove_item", {"entity_id": self.entity_id, "item": [uid]}, blocking=True
        )
