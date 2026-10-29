"""Small async client for the Mealie shopping list API (Mealie 3.x)."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .core.foods import FoodRef
from .core.models import SrcItem, SrcNew
from .core.units import norm


class MealieError(Exception):
    """Mealie could not be reached or answered with an error."""


class MealieAuthError(MealieError):
    """The token was rejected."""


class MealieClient:
    def __init__(self, session: ClientSession, url: str, token: str) -> None:
        self._session = session
        self._base = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._raw: dict[str, dict[str, Any]] = {}  # item id -> last raw item (needed for updates)
        self._units: dict[str, str] = {}  # normalised unit name -> unit id

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self._session.request(
                method, f"{self._base}{path}", headers=self._headers, timeout=ClientTimeout(total=30), **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    raise MealieAuthError("token rejected")
                if resp.status >= 400:
                    raise MealieError(f"{method} {path}: HTTP {resp.status}")
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        except ClientError as err:
            raise MealieError(f"{method} {path}: {err}") from err
        except TimeoutError as err:
            raise MealieError(f"{method} {path}: timeout") from err

    async def _paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._request("GET", path, params={**(params or {}), "perPage": 200, "page": page})
            out += data.get("items", [])
            if page >= int(data.get("total_pages") or 1):
                return out
            page += 1

    # --- reading
    async def lists(self) -> list[dict[str, Any]]:
        return [{"id": r["id"], "name": r["name"]} for r in await self._paged("/api/households/shopping/lists")]

    async def foods(self) -> list[FoodRef]:
        raw = await self._paged("/api/foods")
        return [
            FoodRef(r["id"], r["name"], tuple(a["name"] for a in r.get("aliases") or [] if a.get("name")))
            for r in raw
        ]

    async def units(self) -> list[dict[str, Any]]:
        raw = await self._paged("/api/units")
        self._units = {}
        for r in raw:
            self._units[norm(r["name"])] = r["id"]
        return raw

    async def items(self) -> dict[str, list[SrcItem]]:
        """All shopping items of the household, grouped by list id."""
        raw = await self._paged("/api/households/shopping/items")
        self._raw = {r["id"]: r for r in raw}
        out: dict[str, list[SrcItem]] = {}
        for r in raw:
            food, unit = r.get("food"), r.get("unit")
            qty = r.get("quantity")
            out.setdefault(r["shoppingListId"], []).append(
                SrcItem(
                    id=r["id"],
                    list_id=r["shoppingListId"],
                    food_id=r.get("foodId"),
                    food=food["name"] if food else None,
                    unit=unit["name"] if unit else None,
                    qty=qty if qty and qty > 0 else None,
                    note=r.get("note") or "",
                    checked=bool(r.get("checked")),
                )
            )
        return out

    # --- writing
    async def create_item(self, n: SrcNew) -> str:
        """Create one item. Mealie may merge it into an existing item; that item's id is returned."""
        body: dict[str, Any] = {"shoppingListId": n.list_id, "checked": False, "note": n.note or ""}
        if n.food_id:
            body["foodId"] = n.food_id
        note = n.note or ""
        if n.unit:
            unit_id = self._units.get(norm(n.unit))
            if unit_id:
                body["unitId"] = unit_id
            elif not n.food_id:
                note = f"{n.unit} {note}".strip()
        body["note"] = note
        body["quantity"] = n.qty if n.qty is not None else (1.0 if not n.food_id else 0.0)
        data = await self._request("POST", "/api/households/shopping/items", json=body)
        created = data.get("createdItems") or []
        updated = data.get("updatedItems") or []
        found = created or updated
        if not found:
            raise MealieError("create returned no item")
        return found[0]["id"]

    async def set_checked(self, ids: list[str], checked: bool) -> None:
        bodies = []
        for i in ids:
            raw = self._raw.get(i)
            if raw is None:
                continue
            bodies.append(
                {
                    "id": i,
                    "shoppingListId": raw["shoppingListId"],
                    "checked": checked,
                    "quantity": raw.get("quantity") or 0,
                    "note": raw.get("note") or "",
                    "foodId": raw.get("foodId"),
                    "unitId": raw.get("unitId"),
                    "labelId": raw.get("labelId"),
                    "position": raw.get("position", 0),
                    "extras": raw.get("extras") or {},
                }
            )
        if bodies:
            await self._request("PUT", "/api/households/shopping/items", json=bodies)

    async def delete(self, ids: list[str]) -> None:
        if ids:
            await self._request("DELETE", "/api/households/shopping/items", params=[("ids", i) for i in ids])
