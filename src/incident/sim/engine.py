"""Assemble a Dataset and its answer key from a recipe."""

import random
from datetime import datetime, timedelta

from incident.models import Change, Dataset, Incident, QueueDef, Topology
from incident.sim.logs import build_logs
from incident.sim.recipe import Fault, Recipe
from incident.sim.series import build_series, finalize
from incident.sim.truth import Selector, Truth, TruthFault
from incident.sim.world import World

ROUTINE_NOTES = ["dependency bump", "log level tweak", "minor copy change", "metrics label rename"]


def _at(recipe: Recipe, minute: int) -> datetime:
    return recipe.start + timedelta(minutes=minute)


def _changes(world: World, recipe: Recipe, rng: random.Random) -> list[Change]:
    out = [
        Change(
            ts=_at(recipe, f.at_min + c.offset_min),
            kind=c.kind,
            service=c.service,
            ref=c.ref,
            note=c.note,
        )
        for f in recipe.faults
        for c in f.changes
    ]
    onsets = [f.at_min for f in recipe.faults if f.role != "distractor"]
    names = [n for n in world.services if n != "rabbitmq"]
    routine = 0
    for _ in range(40):  # routine deploys keep clear of every real onset
        t = rng.randrange(5, recipe.minutes - 5)
        svc = rng.choice(names)
        ref = f"{svc}-{rng.randrange(100, 999):05d}"
        note = rng.choice(ROUTINE_NOTES)
        if routine < 3 and all(abs(t - o) >= 20 for o in onsets):
            out.append(Change(ts=_at(recipe, t), kind="deploy", service=svc, ref=ref, note=note))
            routine += 1
    return sorted(out, key=lambda c: c.ts)


def _truth_fault(recipe: Recipe, f: Fault) -> TruthFault:
    if f.truth is None or f.role == "distractor":
        raise ValueError(f"fault {f.id}: only primary/secondary faults carry truth")
    return TruthFault(
        id=f.id,
        role=f.role,
        component=f.truth.component,
        cause_type=f.truth.cause_type,
        description=f.truth.description,
        onset=_at(recipe, f.at_min),
        decisive=_selectors(recipe, f),
    )


def _selectors(recipe: Recipe, f: Fault) -> list[Selector]:
    end = _at(recipe, recipe.minutes if f.until_min is None else f.until_min)
    logs = [
        Selector(
            kind="log",
            service=r.service,
            level=r.level,
            contains=r.msg.split("{")[0].strip(),
            start=_at(recipe, f.at_min + r.after_min),
            end=end,
        )
        for r in f.logs
        if r.decisive
    ]
    changes = [
        Selector(
            kind="change",
            service=c.service,
            contains=c.ref,
            start=_at(recipe, f.at_min + c.offset_min),
            end=end,
        )
        for c in f.changes
    ]
    metrics = [
        Selector(
            kind="metric",
            service=e.target,
            metric=e.metric,
            min_value=0.8 * e.value,
            start=_at(recipe, f.at_min + e.after_min),
            end=end,
        )
        for e in f.effects
        if e.decisive
    ]
    return logs + changes + metrics


def simulate(world: World, recipe: Recipe) -> tuple[Dataset, Truth]:
    rng = random.Random(recipe.seed)
    series = build_series(world, recipe, rng)
    queues = [
        QueueDef(name=q.name, publisher=q.publisher, consumer=q.consumer) for q in world.queues
    ]
    data = Dataset(
        incident=Incident(
            reported_at=_at(recipe, recipe.incident_at_min), text=recipe.incident_text
        ),
        start=recipe.start,
        minutes=recipe.minutes,
        topology=Topology(
            services=list(world.services), edges=world.edges + recipe.extra_edges, queues=queues
        ),
        logs=build_logs(world, recipe, series, rng),
        metrics=finalize(series, recipe.artifacts),
        changes=_changes(world, recipe, rng),
        history=world.history + recipe.history_extra,
        tool_faults=recipe.tool_faults,
    )
    faults = [_truth_fault(recipe, f) for f in recipe.faults if f.role != "distractor"]
    truth = Truth(
        faults=faults,
        answerable=recipe.answerable,
        expected_status=recipe.expected_status,
        trap=recipe.trap,
    )
    return data, truth
