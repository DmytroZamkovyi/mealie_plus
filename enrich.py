"""Optional AI enrichment of Mealie data through the Home Assistant `ai_task` action.

Only empty things are filled; nothing that already has a value is overwritten. The AI
key stays in the Home Assistant AI integration, this integration never sees it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    AI_RETRY_DAYS,
    CONF_AI_ALIASES,
    CONF_AI_DESCRIPTIONS,
    CONF_AI_ENTITY,
    CONF_AI_IMAGE_ENTITY,
    CONF_AI_IMAGE_LIMIT,
    CONF_AI_IMAGES,
    CONF_AI_LABELS,
    CONF_AI_LIMIT,
    CONF_AI_NUTRITION,
    CONF_AI_TOOLS,
    CONF_AI_UNITS,
    DEFAULT_AI_IMAGE_LIMIT,
    DEFAULT_AI_LIMIT,
    DOMAIN,
    STORE_VERSION,
)
from .core import enrich as core
from .core.units import norm
from .mealie import MealieClient

_LOGGER = logging.getLogger(__name__)
BATCH = 30
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class Enricher:
    def __init__(self, hass: HomeAssistant, entry, client: MealieClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self._lock = asyncio.Lock()
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.enrich")
        self._tried: dict[str, str] = {}

    @property
    def _opts(self):
        return self.entry.options

    def _on(self, key: str) -> bool:
        return bool(self._opts.get(key, False))

    # --- bookkeeping: what was already tried recently
    async def async_load(self) -> None:
        self._tried = dict((await self._store.async_load()) or {})

    async def async_remove_store(self) -> None:
        await self._store.async_remove()

    def _fresh(self, key: str) -> bool:
        ts = self._tried.get(key)
        if not ts:
            return False
        try:
            return dt_util.utcnow() - datetime.fromisoformat(ts) < timedelta(days=AI_RETRY_DAYS)
        except ValueError:
            return False

    def _mark(self, key: str) -> None:
        self._tried[key] = dt_util.utcnow().isoformat()

    # --- ai_task
    async def _ask(self, name: str, instructions: str) -> Any:
        data: dict[str, Any] = {"task_name": name, "instructions": instructions}
        if entity := self._opts.get(CONF_AI_ENTITY):
            data["entity_id"] = entity
        resp = await self.hass.services.async_call(
            "ai_task", "generate_data", data, blocking=True, return_response=True
        )
        return core.parse_json((resp or {}).get("data"))

    async def _image(self, instructions: str) -> tuple[bytes, str, str] | None:
        data: dict[str, Any] = {"task_name": "Mealie Plus recipe image", "instructions": instructions}
        if entity := self._opts.get(CONF_AI_IMAGE_ENTITY) or self._opts.get(CONF_AI_ENTITY):
            data["entity_id"] = entity
        resp = await self.hass.services.async_call(
            "ai_task", "generate_image", data, blocking=True, return_response=True
        )
        url = (resp or {}).get("url")
        if not url:
            return None
        if url.startswith("/"):
            try:
                url = get_url(self.hass, allow_external=False) + url
            except NoURLAvailableError:
                url = get_url(self.hass) + url
        async with async_get_clientsession(self.hass).get(url) as r:
            if r.status != 200:
                return None
            body = await r.read()
        if not body or len(body) > MAX_IMAGE_BYTES:
            return None
        mime = (resp or {}).get("mime_type") or "image/png"
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        return body, ext, mime

    # --- run
    async def async_run(self) -> dict[str, int]:
        if self._lock.locked():
            return {}
        async with self._lock:
            counts = {"foods": 0, "units": 0, "recipes": 0, "images": 0}
            limit = int(self._opts.get(CONF_AI_LIMIT, DEFAULT_AI_LIMIT))
            for name, step, enabled in (
                ("foods", self._foods, self._on(CONF_AI_LABELS) or self._on(CONF_AI_ALIASES)),
                ("units", self._units, self._on(CONF_AI_UNITS)),
                ("recipes", self._recipes, any(self._on(k) for k in (CONF_AI_DESCRIPTIONS, CONF_AI_NUTRITION, CONF_AI_TOOLS, CONF_AI_IMAGES))),
            ):
                if not enabled:
                    continue
                try:
                    result = await step(limit)
                except Exception as err:  # noqa: BLE001  one failing step must not stop the others
                    _LOGGER.warning("AI enrichment step %s failed: %s", name, err)
                    continue
                if isinstance(result, tuple):
                    counts["recipes"], counts["images"] = result
                else:
                    counts[name] = result
            # forget old marks
            self._tried = {k: v for k, v in self._tried.items() if self._fresh(k)}
            await self._store.async_save(self._tried)
            _LOGGER.info("AI enrichment done: %s", counts)
            return counts

    # --- foods: labels and aliases
    async def _foods(self, limit: int) -> int:
        want_labels, want_aliases = self._on(CONF_AI_LABELS), self._on(CONF_AI_ALIASES)
        raw = await self.client.foods_raw()
        labels = await self.client.labels() if want_labels else {}
        want_labels = want_labels and bool(labels)
        taken: set[str] = set()
        for f in raw:
            taken.add(norm(f["name"]))
            taken |= {norm(a["name"]) for a in f.get("aliases") or [] if a.get("name")}
        todo = [
            f
            for f in raw
            if not self._fresh(f"food:{f['id']}")
            and ((want_labels and not f.get("labelId")) or (want_aliases and not f.get("aliases")))
        ][:limit]
        done = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            names = [f["name"].replace("\n", " ").strip() for f in batch]
            answer = await self._ask(
                "Mealie Plus foods", core.food_prompt(names, list(labels), want_labels, want_aliases)
            )
            patches = core.validate_foods(
                answer, [(f["id"], f["name"]) for f in batch], labels, taken, want_labels, want_aliases
            )
            for f in batch:
                self._mark(f"food:{f['id']}")
                patch = patches.get(f["id"])
                if not patch:
                    continue
                # only what is still empty is applied
                label = patch.label_id if not f.get("labelId") else None
                aliases = patch.aliases if not f.get("aliases") else []
                if label or aliases:
                    await self.client.update_food(f, label, aliases)
                    taken |= {norm(a) for a in aliases}
                    done += 1
        return done

    # --- units for shopping items
    async def _units(self, limit: int) -> int:
        units = {u["name"]: u["id"] for u in await self.client.units()}
        await self.client.items()  # refreshes the raw items
        todo = [r for r in self.client.unitless_items() if not self._fresh(f"item:{r['id']}")][:limit]
        done = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            answer = await self._ask(
                "Mealie Plus units",
                core.unit_prompt([(r["food"]["name"].replace("\n", " "), r["quantity"]) for r in batch], list(units)),
            )
            chosen = core.validate_units(answer, [r["id"] for r in batch], units)
            for r in batch:
                self._mark(f"item:{r['id']}")
            if chosen:
                await self.client.set_units(chosen)
                done += len(chosen)
        return done

    # --- recipes
    async def _recipes(self, limit: int) -> tuple[int, int]:
        want_desc = self._on(CONF_AI_DESCRIPTIONS)
        want_nut = self._on(CONF_AI_NUTRITION)
        want_tools = self._on(CONF_AI_TOOLS)
        want_img = self._on(CONF_AI_IMAGES)
        image_limit = int(self._opts.get(CONF_AI_IMAGE_LIMIT, DEFAULT_AI_IMAGE_LIMIT))
        tools = {t["name"]: t for t in await self.client.tools()} if want_tools else {}
        recipes = 0
        images = 0
        for summary in await self.client.recipe_summaries():
            if recipes >= limit and images >= image_limit:
                break
            rid, slug = summary.get("id"), summary.get("slug")
            if not rid or not slug:
                continue
            text_key, image_key = f"recipe:{rid}", f"image:{rid}"
            do_text = recipes < limit and not self._fresh(text_key)
            do_image = want_img and images < image_limit and not self._fresh(image_key) and not summary.get("image")
            if not (do_text or do_image):
                continue
            recipe = await self.client.recipe(slug)
            ingredients = [
                (i.get("display") or i.get("originalText") or i.get("note") or "").strip()
                for i in recipe.get("recipeIngredient") or []
            ]
            ingredients = [i for i in ingredients if i]
            steps = [
                (s.get("text") or "").strip()[:400]
                for s in recipe.get("recipeInstructions") or []
                if (s.get("text") or "").strip()
            ]

            body: dict[str, Any] = {}
            if do_text:
                need_desc = want_desc and not (recipe.get("description") or "").strip()
                need_keys = core.empty_nutrition_keys(recipe.get("nutrition")) if want_nut else []
                need_tools = want_tools and not recipe.get("tools")
                if need_desc or need_keys or need_tools:
                    answer = await self._ask(
                        "Mealie Plus recipe",
                        core.recipe_prompt(
                            recipe["name"], ingredients, recipe.get("recipeServings") or recipe.get("recipeYield"),
                            list(tools), need_desc, need_keys, need_tools, steps,
                        ),
                    )
                    patch = core.validate_recipe(answer, need_desc, need_keys, need_tools)
                    if patch.description:
                        body["description"] = patch.description
                    if patch.nutrition:
                        body["nutrition"] = {**(recipe.get("nutrition") or {}), **patch.nutrition}
                    if patch.tools:
                        chosen = []
                        for name in patch.tools:
                            tool = tools.get(name) or next((t for k, t in tools.items() if norm(k) == norm(name)), None)
                            if tool is None:
                                tool = await self.client.create_tool(name)
                                tools[tool["name"]] = tool
                            chosen.append({k: tool[k] for k in ("id", "name", "slug") if k in tool})
                        body["tools"] = chosen
                    if body:
                        await self.client.patch_recipe(slug, body)
                    recipes += 1
                self._mark(text_key)
                description = body.get("description") if need_desc and body else None
            else:
                description = None

            if do_image:
                self._mark(image_key)
                made = await self._image(
                    core.image_prompt(recipe["name"], description or recipe.get("description"), ingredients)
                )
                if made:
                    data, ext, mime = made
                    await self.client.upload_image(slug, data, ext, mime)
                    images += 1
        return recipes, images
