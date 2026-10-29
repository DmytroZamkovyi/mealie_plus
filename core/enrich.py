"""AI enrichment: prompts and strict validation of answers. No Home Assistant, no network.

Rules that hold everywhere:
- only empty things are filled, nothing that already has a value is ever overwritten;
- an answer is accepted only if it matches what Mealie already knows (labels and units by
  exact name), anything else is dropped;
- the model answers by short numbers (indexes), never by Mealie ids, so a garbled id
  cannot touch the wrong object.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .units import norm

NUTRITION_KEYS = (
    "calories",
    "carbohydrateContent",
    "cholesterolContent",
    "fatContent",
    "fiberContent",
    "proteinContent",
    "saturatedFatContent",
    "sodiumContent",
    "sugarContent",
    "transFatContent",
    "unsaturatedFatContent",
)
MAX_ALIASES = 4


def parse_json(text: Any) -> Any:
    """Model text to JSON; tolerates code fences and text around the JSON."""
    if isinstance(text, (dict, list)):
        return text
    s = str(text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S)
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = s.find(opener), s.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(s[a : b + 1])
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------- foods

@dataclass
class FoodPatch:
    label_id: str | None = None
    aliases: list[str] = field(default_factory=list)


def food_prompt(foods: list[str], labels: list[str], want_labels: bool, want_aliases: bool) -> str:
    lines = [f"{i}: {name}" for i, name in enumerate(foods)]
    parts = [
        "You help tidy a household grocery database (Ukrainian). For each numbered food return JSON.",
        'Answer ONLY with a JSON object: {"<number>": {...}} for every number.',
    ]
    fields = []
    if want_labels:
        fields.append(
            '"label": the store section, exactly one of these names or null if none fits: ' + json.dumps(labels, ensure_ascii=False)
        )
    if want_aliases:
        fields.append(
            f'"aliases": up to {MAX_ALIASES} other short names people use for the same grocery product (synonyms, other '
            "forms), lowercase Ukrainian, no quantities and no units, [] if unsure"
        )
    parts.append("Each value has: " + "; ".join(fields) + ".")
    parts.append("Foods:\n" + "\n".join(lines))
    return "\n".join(parts)


def validate_foods(
    answer: Any,
    foods: list[tuple[str, str]],  # (food id, name) in prompt order
    labels: dict[str, str],  # label name -> label id
    taken_names: set[str],  # normalised names and aliases of all foods
    want_labels: bool,
    want_aliases: bool,
) -> dict[str, FoodPatch]:
    out: dict[str, FoodPatch] = {}
    if not isinstance(answer, dict):
        return out
    by_label = {norm(k): v for k, v in labels.items()}
    for key, value in answer.items():
        try:
            food_id, name = foods[int(key)]
        except (ValueError, IndexError, TypeError):
            continue
        if not isinstance(value, dict):
            continue
        patch = FoodPatch()
        if want_labels:
            label = value.get("label")
            if isinstance(label, str) and norm(label) in by_label:
                patch.label_id = by_label[norm(label)]
        if want_aliases and isinstance(value.get("aliases"), list):
            seen = set(taken_names)
            for a in value["aliases"]:
                if not isinstance(a, str):
                    continue
                a = re.sub(r"\s+", " ", a).strip().lower()
                if not a or len(a) > 40 or any(ch.isdigit() for ch in a) or norm(a) in seen:
                    continue
                seen.add(norm(a))
                patch.aliases.append(a)
                if len(patch.aliases) >= MAX_ALIASES:
                    break
        if patch.label_id or patch.aliases:
            out[food_id] = patch
    return out


# ---------------------------------------------------------------- shopping items without a unit

def unit_prompt(items: list[tuple[str, float]], units: list[str]) -> str:
    lines = [f"{i}: {qty:g} x {food}" for i, (food, qty) in enumerate(items)]
    return (
        "For each numbered grocery list line choose the most natural unit the amount is counted in. "
        'Answer ONLY with a JSON object {"<number>": "<unit>"}, the unit exactly one of '
        + json.dumps(units, ensure_ascii=False)
        + ", or null if the amount is a plain count of pieces with no unit or you are unsure.\n"
        + "\n".join(lines)
    )


def validate_units(answer: Any, items: list[str], units: dict[str, str]) -> dict[str, str]:
    """-> {item id: unit id}. `items` are item ids in prompt order, `units` maps unit name -> unit id."""
    out: dict[str, str] = {}
    if not isinstance(answer, dict):
        return out
    by_name = {norm(k): v for k, v in units.items()}
    for key, value in answer.items():
        try:
            item_id = items[int(key)]
        except (ValueError, IndexError, TypeError):
            continue
        if isinstance(value, str) and norm(value) in by_name:
            out[item_id] = by_name[norm(value)]
    return out


# ---------------------------------------------------------------- recipes

def empty_nutrition_keys(nutrition: dict | None) -> list[str]:
    n = nutrition or {}
    return [k for k in NUTRITION_KEYS if n.get(k) in (None, "")]


def recipe_prompt(
    name: str,
    ingredients: list[str],
    servings: float | None,
    tool_names: list[str],
    want_description: bool,
    want_nutrition: list[str],
    want_tools: bool,
) -> str:
    fields = []
    if want_description:
        fields.append('"description": one or two plain sentences describing the dish (Ukrainian), no markdown')
    if want_nutrition:
        fields.append(
            '"nutrition": an object with numeric values per ONE serving for exactly these keys: '
            + json.dumps(want_nutrition)
            + " (calories in kcal, fats/carbs/protein/fiber/sugar in grams, cholesterol and sodium in milligrams); a rough estimate is fine"
        )
    if want_tools:
        fields.append(
            '"tools": up to 4 kitchen tools needed, preferably chosen from '
            + json.dumps(tool_names, ensure_ascii=False)
            + " (new short Ukrainian names are allowed), [] if none are special"
        )
    return (
        "You help fill in a recipe card. Answer ONLY with a JSON object with these fields: "
        + "; ".join(fields)
        + f".\nRecipe: {name}\nServings: {servings or 'unknown'}\nIngredients:\n"
        + "\n".join(f"- {i}" for i in ingredients[:40])
    )


@dataclass
class RecipePatch:
    description: str | None = None
    nutrition: dict[str, str] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.description or self.nutrition or self.tools)


def _number(v: Any) -> str | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    elif isinstance(v, str):
        m = re.match(r"^\s*(\d+(?:[.,]\d+)?)", v)
        if not m:
            return None
        n = float(m.group(1).replace(",", "."))
    else:
        return None
    if n < 0 or n > 100000:
        return None
    if n >= 10 or abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.1f}"


def validate_recipe(
    answer: Any, want_description: bool, want_nutrition: list[str], want_tools: bool
) -> RecipePatch:
    patch = RecipePatch()
    if not isinstance(answer, dict):
        return patch
    d = answer.get("description")
    if want_description and isinstance(d, str) and d.strip():
        patch.description = re.sub(r"\s+", " ", d).strip()[:500]
    n = answer.get("nutrition")
    if want_nutrition and isinstance(n, dict):
        for k in want_nutrition:
            v = _number(n.get(k))
            if v is not None:
                patch.nutrition[k] = v
    t = answer.get("tools")
    if want_tools and isinstance(t, list):
        seen: set[str] = set()
        for x in t:
            if isinstance(x, str):
                x = re.sub(r"\s+", " ", x).strip()
                if 0 < len(x) <= 30 and norm(x) not in seen:
                    seen.add(norm(x))
                    patch.tools.append(x)
            if len(patch.tools) >= 4:
                break
    return patch


def image_prompt(name: str, description: str | None, ingredients: list[str]) -> str:
    main = ", ".join(ingredients[:8])
    return (
        f"Appetizing top-down food photo of the dish \"{name}\" on a plain plate, natural light, no text, no people, no logos."
        + (f" {description}" if description else "")
        + (f" Main ingredients: {main}." if main else "")
    )
