"""Drives the Home Assistant enrichment runner with stubbed Home Assistant modules."""

import asyncio
import json
import sys
import types
from datetime import datetime, timezone


def _stub_homeassistant():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class Store:
        data = {}

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return Store.data.get(self.key)

        async def async_save(self, data):
            Store.data[self.key] = data

        async def async_remove(self):
            Store.data.pop(self.key, None)

    mod("homeassistant")
    mod("homeassistant.core", HomeAssistant=object)
    mod("homeassistant.helpers")
    mod("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
    mod("homeassistant.helpers.network", NoURLAvailableError=Exception, get_url=lambda *a, **k: "http://ha")
    mod("homeassistant.helpers.storage", Store=Store)
    mod("homeassistant.util")
    mod("homeassistant.util.dt", utcnow=lambda: datetime(2026, 10, 30, tzinfo=timezone.utc))
    sys.modules["homeassistant"].util = sys.modules["homeassistant.util"]
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]


_stub_homeassistant()

from custom_components.shopping_sync.enrich import Enricher  # noqa: E402


class Services:
    def __init__(self, answers):
        self.answers = answers  # task_name -> data text
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False, return_response=False):
        self.calls.append((service, data["task_name"]))
        return {"data": self.answers.get(data["task_name"], "{}")}


class Hass:
    def __init__(self, answers):
        self.services = Services(answers)


class Entry:
    entry_id = "e1"

    def __init__(self, **options):
        self.options = options


class Client:
    def __init__(self):
        self.foods = [
            {"id": "f1", "name": "морква", "labelId": None, "aliases": [], "extras": {}},
            {"id": "f2", "name": "сир", "labelId": "L2", "aliases": [{"name": "сирок"}], "extras": {}},
        ]
        self.updated = []
        self.units_set = {}
        self.items_raw = {
            "i1": {"id": "i1", "food": {"name": "картопля"}, "quantity": 2, "unitId": None, "checked": False},
            "i2": {"id": "i2", "food": {"name": "сіль"}, "quantity": 1, "unitId": "U9", "checked": False},
        }
        self.recipe_patches = []
        self.created_tools = []
        self.uploads = []

    async def foods_raw(self):
        return self.foods

    async def labels(self):
        return {"Овочі": "L1", "Молочні": "L2"}

    async def update_food(self, raw, label_id, aliases):
        self.updated.append((raw["id"], label_id, aliases))

    async def units(self):
        return [{"id": "U1", "name": "штука"}, {"id": "U9", "name": "г"}]

    async def items(self):
        return {}

    def unitless_items(self):
        return [r for r in self.items_raw.values() if not r["unitId"]]

    async def set_units(self, m):
        self.units_set.update(m)

    async def tools(self):
        return [{"id": "T1", "name": "Каструля", "slug": "kastrulya"}]

    async def create_tool(self, name):
        self.created_tools.append(name)
        return {"id": "T2", "name": name, "slug": name.lower()}

    async def recipe_summaries(self):
        return [
            {"id": "r1", "slug": "borsch", "image": None},
            {"id": "r2", "slug": "done", "image": "x"},
        ]

    async def recipe(self, slug):
        if slug == "borsch":
            return {"name": "Борщ", "slug": slug, "description": "", "tools": [], "nutrition": {"calories": "300"},
                    "recipeIngredient": [{"display": "1 буряк"}], "recipeServings": 4}
        return {"name": "Готово", "slug": slug, "description": "Є опис", "tools": [{"id": "T1"}],
                "nutrition": {k: "1" for k in ["calories", "carbohydrateContent", "cholesterolContent", "fatContent",
                "fiberContent", "proteinContent", "saturatedFatContent", "sodiumContent", "sugarContent",
                "transFatContent", "unsaturatedFatContent"]}, "recipeIngredient": []}

    async def patch_recipe(self, slug, body):
        self.recipe_patches.append((slug, body))

    async def upload_image(self, slug, data, ext, mime):
        self.uploads.append((slug, ext))


def run(opts, answers):
    hass, client = Hass(answers), Client()
    e = Enricher(hass, Entry(**opts), client)
    counts = asyncio.run(e.async_run())
    return hass, client, e, counts


def test_foods_only_empty_things_are_filled():
    ans = {"Shopping Sync foods": json.dumps({"0": {"label": "Овочі", "aliases": ["корінь"]}, "1": {"label": "Овочі", "aliases": ["твердий сир"]}})}
    _, client, _, counts = run({"ai_labels": True, "ai_aliases": True}, ans)
    # f1 has neither label nor aliases; f2 has both and is not even asked about
    assert client.updated == [("f1", "L1", ["корінь"])]
    assert counts["foods"] == 1


def test_units_are_set_only_for_unitless_items():
    ans = {"Shopping Sync units": json.dumps({"0": "штука"})}
    hass, client, _, counts = run({"ai_units": True}, ans)
    assert client.units_set == {"i1": "U1"} and counts["units"] == 1


def test_recipe_text_fills_only_empty_fields_and_creates_missing_tools():
    ans = {"Shopping Sync recipe": json.dumps({
        "description": "Червоний суп.",
        "nutrition": {"calories": 999, "proteinContent": 5, "fatContent": 7},
        "tools": ["Каструля", "Блендер"],
    })}
    hass, client, _, counts = run({"ai_descriptions": True, "ai_nutrition": True, "ai_tools": True}, ans)
    assert len(client.recipe_patches) == 1 and counts["recipes"] == 1  # the complete recipe asks nothing
    slug, body = client.recipe_patches[0]
    assert slug == "borsch" and body["description"] == "Червоний суп."
    assert body["nutrition"]["calories"] == "300"  # existing value kept
    assert body["nutrition"]["proteinContent"] == "5"
    assert [t["name"] for t in body["tools"]] == ["Каструля", "Блендер"] and client.created_tools == ["Блендер"]


def test_nothing_is_asked_twice_within_the_retry_window():
    ans = {"Shopping Sync foods": "{}"}
    hass = Hass(ans)
    client = Client()
    e = Enricher(hass, Entry(ai_labels=True), client)
    asyncio.run(e.async_run())
    asyncio.run(e.async_run())
    assert len([c for c in hass.services.calls if c[1] == "Shopping Sync foods"]) == 1


def test_garbage_answer_changes_nothing():
    _, client, _, counts = run({"ai_labels": True, "ai_aliases": True}, {"Shopping Sync foods": "вибачте, не можу"})
    assert client.updated == [] and counts["foods"] == 0
