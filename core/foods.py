"""Food dictionary: resolve typed text to a Mealie food, tolerant to Ukrainian endings."""

from __future__ import annotations

from dataclasses import dataclass, field

from .parse import parse
from .units import norm


@dataclass(frozen=True)
class FoodRef:
    id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass
class Resolution:
    kind: str  # "exact" | "stem" | "ambiguous" | "none"
    food: FoodRef | None = None
    candidates: list[FoodRef] = field(default_factory=list)


def stem_key(text: str) -> str:
    """Crude stem: drop the last two letters of words longer than three letters."""
    words = norm(text).split()
    return " ".join(w if len(w) <= 3 else w[: max(3, len(w) - 2)] for w in words)


def _dedupe(foods: list[FoodRef]) -> list[FoodRef]:
    seen: dict[str, FoodRef] = {}
    for f in foods:
        seen.setdefault(f.id, f)
    return list(seen.values())


class FoodIndex:
    """Index over names and aliases. Mealie aliases often carry a quantity or a
    unit ("ст. ложка Мед"), so aliases are cleaned with the same parser."""

    def __init__(self, foods: list[FoodRef], extra_aliases: dict[str, str] | None = None) -> None:
        self._by_exact: dict[str, list[FoodRef]] = {}
        self._by_stem: dict[str, list[FoodRef]] = {}
        by_id = {f.id: f for f in foods}
        for f in foods:
            names = {norm(f.name)}
            for a in f.aliases:
                cleaned = parse(a).food_text or norm(a)
                names.add(norm(cleaned))
            for n in names:
                if n:
                    self._by_exact.setdefault(n, []).append(f)
                    self._by_stem.setdefault(stem_key(n), []).append(f)
        # user-confirmed aliases: text -> food id
        for text, food_id in (extra_aliases or {}).items():
            f = by_id.get(food_id)
            if f:
                n = norm(text)
                self._by_exact.setdefault(n, []).insert(0, f)
                self._by_stem.setdefault(stem_key(n), []).insert(0, f)

    def resolve(self, text: str) -> Resolution:
        q = norm(text)
        if not q:
            return Resolution("none")
        for kind, found in (("exact", self._by_exact.get(q)), ("stem", self._by_stem.get(stem_key(q)))):
            if not found:
                continue
            cands = _dedupe(found)
            if len(cands) == 1:
                return Resolution(kind, cands[0], cands)
            named = [c for c in cands if norm(c.name) == q]
            if len(named) == 1:
                return Resolution(kind, named[0], cands)
            return Resolution("ambiguous", None, cands)
        return Resolution("none")
