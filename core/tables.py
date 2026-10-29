"""All lookup tables the engine needs, with user overrides merged in."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import data
from .foods import FoodIndex
from .units import norm


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()


@dataclass
class Tables:
    foods: FoodIndex | None = None
    synonyms: dict[str, str] = field(default_factory=dict)  # variant -> canonical (both normalised)
    base_equiv: dict[str, dict[str, tuple[str, float]]] = field(default_factory=dict)
    food_bridges: dict[str, dict[tuple[str, str], float]] = field(default_factory=dict)
    global_bridges: dict[tuple[str, str], float] = field(default_factory=dict)
    extra_unit_aliases: dict[str, str] = field(default_factory=dict)  # unit_key -> unit name

    def food_key(self, name: str) -> str:
        n = norm(name)
        return self.synonyms.get(n, n)

    def display_name(self, name: str) -> str:
        key = self.food_key(name)
        shown = key if key != norm(name) else clean_name(name)
        return shown[:1].upper() + shown[1:]


def default_tables(
    foods: FoodIndex | None = None,
    extra_synonyms: dict[str, list[str]] | None = None,
    extra_unit_aliases: dict[str, str] | None = None,
    extra_equiv: dict[str, dict[str, tuple[str, float]]] | None = None,
) -> Tables:
    synonyms: dict[str, str] = {}
    groups = {**data.SYNONYMS, **{k: tuple(v) for k, v in (extra_synonyms or {}).items()}}
    for canonical, variants in groups.items():
        c = norm(canonical)
        synonyms[c] = c
        for v in variants:
            synonyms[norm(v)] = c
    equiv = {k: dict(v) for k, v in data.BASE_EQUIV.items()}
    for food, d in (extra_equiv or {}).items():
        equiv.setdefault(norm(food), {}).update(d)
    return Tables(
        foods=foods,
        synonyms=synonyms,
        base_equiv=equiv,
        food_bridges={k: dict(v) for k, v in data.FOOD_BRIDGES.items()},
        global_bridges=dict(data.GLOBAL_BRIDGES),
        extra_unit_aliases=dict(extra_unit_aliases or {}),
    )
