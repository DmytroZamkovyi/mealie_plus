"""A sync group: one source list (Mealie) mirrored into any number of targets.

A target is anything that can show the merged lines and report ticks: a Home Assistant
`todo` entity, or an external platform behind the same small interface. Every target
keeps its own link table; the source is the hub, so a tick in one target reaches the
source and, in the same cycle, all targets processed after it (the rest on the next).

Safety rules:
- A target that cannot be read is skipped. An unreadable list is never treated as an
  empty one, otherwise every line would look deleted.
- A target that left the group simply loses its state; nothing is deleted anywhere.
- The weekly purge of ticked items runs once per group, not once per target.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

from .engine import ExecResult, SourceApi, TargetApi, execute, plan_sync
from .models import Config, HaItem, Issue, Plan, SrcItem, State
from .tables import Tables


class SourcePlatform(SourceApi, Protocol):
    """The list everything is merged from (Mealie)."""

    async def items(self) -> list[SrcItem]: ...


class TargetPlatform(TargetApi, Protocol):
    """A list that mirrors the merged lines (a Home Assistant to-do list, an external platform).

    `items()` must raise when the list cannot be read right now.
    """

    async def items(self) -> list[HaItem]: ...


@dataclass
class GroupState:
    targets: dict[str, State] = field(default_factory=dict)
    last_purge: str | None = None

    def to_json(self) -> dict:
        return {"targets": {k: v.to_json() for k, v in self.targets.items()}, "last_purge": self.last_purge}

    @classmethod
    def from_json(cls, raw: dict | None) -> "GroupState":
        raw = raw or {}
        return cls(
            targets={k: State.from_json(v) for k, v in (raw.get("targets") or {}).items()},
            last_purge=raw.get("last_purge"),
        )


@dataclass
class GroupResult:
    state: GroupState
    plans: dict[str, Plan] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    purged: int = 0
    skipped: list[str] = field(default_factory=list)  # targets that could not be read


async def sync_group(
    source: SourcePlatform,
    targets: dict[str, TargetPlatform],
    state: GroupState,
    cfg: Config,
    tables: Tables,
    now: datetime,
) -> GroupResult:
    new = GroupState(targets={t: s for t, s in state.targets.items() if t in targets}, last_purge=state.last_purge)
    result = GroupResult(state=new)

    # weekly purge of ticked items, once for the whole group
    if cfg.purge_days > 0:
        if new.last_purge is None:
            new.last_purge = now.isoformat()
        elif now - datetime.fromisoformat(new.last_purge) >= timedelta(days=cfg.purge_days):
            ticked = [s.id for s in await source.items() if s.checked]
            if ticked:
                try:
                    await source.delete(ticked)
                    result.purged = len(ticked)
                except Exception as err:  # noqa: BLE001
                    result.errors.append(f"purge: {err}")
            new.last_purge = now.isoformat()

    # targets are handled one after another; the source is re-read between them
    plain = replace(cfg, purge_days=0)
    for tid in sorted(targets):
        target = targets[tid]
        try:
            ha_items = await target.items()
        except Exception as err:  # noqa: BLE001
            result.skipped.append(tid)
            result.errors.append(f"{tid}: cannot read: {err}")
            continue
        src_items = await source.items()
        plan = plan_sync(src_items, ha_items, new.targets.get(tid, State()), plain, tables, now)
        res: ExecResult = await execute(plan, source, target)
        new.targets[tid] = res.state
        result.plans[tid] = plan
        result.errors += [f"{tid}: {e}" for e in res.errors]
        result.issues += plan.issues
    return result
