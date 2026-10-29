"""Two-way sync between source lists (Mealie) and one target list (Home Assistant).

`plan_sync` is pure: it compares both sides with the stored state and returns a Plan
(operations + the new state). `execute` applies a Plan through two small async APIs.

Model: the source is the truth for *what* is needed, the target is where people tick
things off. Source items are merged into lines; each target item is one line and is
linked to the source items it stands for. Ticking a line ticks all of its source items.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

from .merge import Line, build_lines, entry_for_item, render
from .models import Config, HaAdd, HaItem, HaUpdate, Issue, Link, Plan, SrcItem, SrcNew, State
from .parse import parse
from .tables import Tables, clean_name
from .units import TASTE_UNITS


def _typed_to_src(text: str, uid_tmp: str, cfg: Config, tables: Tables, issues: list[Issue], ha_uid: str):
    """Turn text typed in the target into a new source item (and its working copy)."""
    p = parse(text, tables.extra_unit_aliases)
    res = tables.foods.resolve(p.food_text) if tables.foods and p.food_text else None
    if res and res.kind == "ambiguous":
        issues.append(Issue("ambiguous_food", ha_uid, text, res.candidates))
    if res and res.food:
        unit = TASTE_UNITS[0] if p.taste else p.unit
        qty = None if p.taste else p.qty
        new = SrcNew(uid_tmp, cfg.inbox_list_id, res.food.id, res.food.name, unit, qty, "")
        item = SrcItem(uid_tmp, cfg.inbox_list_id, res.food.id, res.food.name, unit, qty, "", False)
    else:
        new = SrcNew(uid_tmp, cfg.inbox_list_id, None, None, None, None, text)
        item = SrcItem(uid_tmp, cfg.inbox_list_id, None, None, None, None, text, False)
    return new, item


def plan_sync(
    src: list[SrcItem],
    ha: list[HaItem],
    state: State,
    cfg: Config,
    tables: Tables,
    now: datetime,
) -> Plan:
    plan = Plan(state=state.copy())
    st = plan.state
    work: dict[str, SrcItem] = {s.id: replace(s) for s in src}
    ha_by = {h.uid: h for h in ha}
    prior_links = len(st.links)

    # A1. lines removed in the target -> delete their source items (with a guard)
    deleted: list[list[str]] = []
    for uid in [u for u in st.links if u not in ha_by]:
        link = st.links.pop(uid)
        ids = [m for m in link.members if m in work]
        if cfg.propagate_deletes and ids:
            deleted.append(ids)
    if deleted:
        limit = max(cfg.delete_guard_min, cfg.delete_guard_ratio * max(prior_links, 1))
        if len(deleted) > limit:
            plan.blocked_deletes = len(deleted)  # lines come back below
        else:
            for ids in deleted:
                plan.src_delete += ids
                for i in ids:
                    work.pop(i, None)

    # A2. ticks in the target -> tick (or untick) all source items of the line
    for uid, link in st.links.items():
        h = ha_by[uid]
        if h.done != link.done:
            ids = [m for m in link.members if m in work]
            if ids:
                plan.src_check.append((ids, h.done))
                for i in ids:
                    work[i].checked = h.done
            link.done = h.done

    # A3. items typed in the target -> new source items in the inbox list
    typed: dict[str, str] = {}  # ha uid -> tmp source id
    if cfg.inbox_list_id:
        for h in ha:
            text = clean_name(h.summary)
            if h.uid in st.links or not text:
                continue
            tmp = f"new:{len(typed) + 1}"
            new, item = _typed_to_src(text, tmp, cfg, tables, plan.issues, h.uid)
            plan.src_create.append(new)
            work[tmp] = item
            typed[h.uid] = tmp

    # B0. weekly purge of checked items
    if cfg.purge_days > 0:
        if st.last_purge is None:
            st.last_purge = now.isoformat()
        elif now - datetime.fromisoformat(st.last_purge) >= timedelta(days=cfg.purge_days):
            ids = [i for i, s in work.items() if s.checked and not i.startswith("new:")]
            plan.src_delete += ids
            for i in ids:
                del work[i]
            plan.purged = len(ids)
            st.last_purge = now.isoformat()

    # B. merge source items into lines (separately for open and ticked items)
    lines: dict[tuple[str, bool], Line] = {}
    for done in (False, True):
        entries = [entry_for_item(s, tables) for s in work.values() if s.checked == done]
        for ln in build_lines(entries, tables):
            lines[(ln.key, done)] = ln

    # C. match lines to target items
    existing: dict[tuple[str, bool], str] = {}
    for uid, l in st.links.items():
        existing.setdefault((l.key, l.done), uid)
    used: set[str] = set()

    def assign(uid: str, key: tuple[str, bool], ln: Line) -> None:
        summary, description = render(ln)
        cur = ha_by.get(uid)
        upd = HaUpdate(uid)
        if cur is None or cur.summary != summary:
            upd.summary = summary
        if cur is None or cur.description != description:
            upd.description = description
        if cur is None or cur.done != key[1]:
            upd.done = key[1]
        if upd.summary is not None or upd.description is not None or upd.done is not None:
            plan.ha_update.append(upd)
        st.links[uid] = Link(ln.key, key[1], list(ln.members), summary, description)
        used.add(uid)

    pending = []
    for key, ln in lines.items():
        uid = existing.get(key)
        if uid and uid not in used:
            assign(uid, key, ln)
        else:
            pending.append((key, ln))

    free = {uid: l for uid, l in st.links.items() if uid not in used}
    after_transition = []
    for key, ln in pending:  # same food, other state: the item was ticked/unticked
        uid = next((u for u, l in free.items() if l.key == ln.key and l.done != key[1]), None)
        if uid:
            del free[uid]
            assign(uid, key, ln)
        else:
            after_transition.append((key, ln))

    by_tmp = {tmp: uid for uid, tmp in typed.items()}
    rest = []
    for key, ln in after_transition:  # a typed item becomes the line it was merged into
        uid = next((by_tmp[m] for m in ln.members if m in by_tmp and by_tmp[m] not in used), None)
        if uid:
            assign(uid, key, ln)
        else:
            rest.append((key, ln))

    for n, (key, ln) in enumerate(rest, 1):
        summary, description = render(ln)
        tmp = f"tmp:{n}"
        plan.ha_add.append(HaAdd(tmp, summary, description, key[1]))
        st.links[tmp] = Link(ln.key, key[1], list(ln.members), summary, description)

    for uid in free:  # lines nothing stands behind any more
        plan.removed_links[uid] = st.links.pop(uid)
        plan.ha_remove.append(uid)
    for uid in typed:  # typed items merged into an existing line
        if uid not in used:
            plan.ha_remove.append(uid)
    plan.typed = typed
    return plan


class SourceApi(Protocol):
    async def create(self, items: list[SrcNew]) -> dict[str, str]: ...
    async def set_checked(self, ids: list[str], checked: bool) -> None: ...
    async def delete(self, ids: list[str]) -> None: ...


class TargetApi(Protocol):
    async def add(self, summary: str, description: str, done: bool) -> str: ...
    async def update(self, uid: str, summary: str | None, description: str | None, done: bool | None) -> None: ...
    async def remove(self, uid: str) -> None: ...


@dataclass
class ExecResult:
    state: State
    errors: list[str] = field(default_factory=list)


async def execute(plan: Plan, src: SourceApi, ha: TargetApi) -> ExecResult:
    st = plan.state
    errors: list[str] = []

    tmpmap: dict[str, str] = {}
    if plan.src_create:
        try:
            tmpmap = await src.create(plan.src_create)
        except Exception as err:  # noqa: BLE001 - a failed step must not stop the others
            errors.append(f"create in source: {err}")
    for link in st.links.values():  # real ids replace temporary ones; failed creations drop out
        link.members = [tmpmap.get(m, m) for m in link.members if not m.startswith("new:") or m in tmpmap]
    # A line with nothing behind it was only backed by items that could not be created:
    # leave the typed item as the person wrote it and retry next cycle.
    dead = {uid for uid, link in st.links.items() if not link.members}
    for uid in dead:
        del st.links[uid]
    failed_typed = {uid for uid, tmp in plan.typed.items() if tmp not in tmpmap}

    for ids, checked in plan.src_check:
        try:
            await src.set_checked(ids, checked)
        except Exception as err:  # noqa: BLE001
            errors.append(f"check in source: {err}")
            for link in st.links.values():
                if set(link.members) & set(ids):
                    link.done = not checked
    if plan.src_delete:
        try:
            await src.delete(plan.src_delete)
        except Exception as err:  # noqa: BLE001
            errors.append(f"delete in source: {err}")

    for uid in plan.ha_remove:
        if uid in failed_typed:
            continue
        try:
            await ha.remove(uid)
        except Exception as err:  # noqa: BLE001
            errors.append(f"remove from target: {err}")
            if uid in plan.removed_links:
                st.links[uid] = plan.removed_links[uid]
    for add in plan.ha_add:
        if add.tmp in dead:
            continue
        link = st.links.pop(add.tmp, None)
        try:
            uid = await ha.add(add.summary, add.description, add.done)
        except Exception as err:  # noqa: BLE001
            errors.append(f"add to target: {err}")
            continue
        if link is not None:
            st.links[uid] = link
    for upd in plan.ha_update:
        if upd.uid in dead:
            continue
        try:
            await ha.update(upd.uid, upd.summary, upd.description, upd.done)
        except Exception as err:  # noqa: BLE001
            errors.append(f"update in target: {err}")
    return ExecResult(st, errors)
