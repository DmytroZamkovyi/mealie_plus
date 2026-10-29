"""Plain data structures shared by the engine and the Home Assistant layer."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .foods import FoodRef


@dataclass
class SrcItem:
    """One item of a source list (Mealie)."""

    id: str
    list_id: str | None
    food_id: str | None
    food: str | None
    unit: str | None
    qty: float | None
    note: str
    checked: bool


@dataclass
class HaItem:
    """One item of the target to-do list (Home Assistant)."""

    uid: str
    summary: str
    description: str
    done: bool


@dataclass
class SrcNew:
    """An item to create in the source (typed in Home Assistant)."""

    tmp: str
    list_id: str | None
    food_id: str | None
    food: str | None
    unit: str | None
    qty: float | None
    note: str


@dataclass
class Link:
    """One line in the target and the source items it stands for."""

    key: str  # "<food key>|<base>"
    done: bool
    members: list[str]
    summary: str
    description: str


@dataclass
class State:
    links: dict[str, Link] = field(default_factory=dict)  # target uid -> link
    last_purge: str | None = None

    def copy(self) -> "State":
        return copy.deepcopy(self)

    def to_json(self) -> dict:
        return {
            "links": {
                uid: {
                    "key": l.key,
                    "done": l.done,
                    "members": l.members,
                    "summary": l.summary,
                    "description": l.description,
                }
                for uid, l in self.links.items()
            },
            "last_purge": self.last_purge,
        }

    @classmethod
    def from_json(cls, raw: dict | None) -> "State":
        raw = raw or {}
        links = {
            uid: Link(d["key"], bool(d["done"]), list(d["members"]), d.get("summary", ""), d.get("description", ""))
            for uid, d in (raw.get("links") or {}).items()
        }
        return cls(links=links, last_purge=raw.get("last_purge"))


@dataclass
class Config:
    inbox_list_id: str | None = None  # where items typed in Home Assistant are created
    propagate_deletes: bool = True
    delete_guard_min: int = 3
    delete_guard_ratio: float = 0.5
    purge_days: int = 7  # remove all checked items every N days; 0 = never


@dataclass
class HaAdd:
    tmp: str
    summary: str
    description: str
    done: bool


@dataclass
class HaUpdate:
    uid: str
    summary: str | None = None
    description: str | None = None
    done: bool | None = None


@dataclass
class Issue:
    kind: str  # "ambiguous_food"
    ha_uid: str
    text: str
    candidates: list[FoodRef] = field(default_factory=list)


@dataclass
class Plan:
    state: State
    ha_add: list[HaAdd] = field(default_factory=list)
    ha_update: list[HaUpdate] = field(default_factory=list)
    ha_remove: list[str] = field(default_factory=list)
    src_check: list[tuple[list[str], bool]] = field(default_factory=list)
    src_create: list[SrcNew] = field(default_factory=list)
    src_delete: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    removed_links: dict[str, Link] = field(default_factory=dict)
    typed: dict[str, str] = field(default_factory=dict)  # target uid typed by a person -> temporary source id
    blocked_deletes: int = 0
    purged: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(
            self.ha_add or self.ha_update or self.ha_remove or self.src_check or self.src_create or self.src_delete
        )
