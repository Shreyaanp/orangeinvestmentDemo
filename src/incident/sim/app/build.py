"""Assemble an application-level Dataset and its answer key from an app recipe."""

import random
from datetime import datetime, timedelta
from pathlib import Path

from incident.app_models import CodeChange, Conversation, StageEvent
from incident.models import Change, Dataset, Incident, LogLine, Topology
from incident.sim.app import repo, telemetry
from incident.sim.app.engine import Sim, run
from incident.sim.app.spec import AppChange, AppFault, AppRecipe, AppWorld, Value
from incident.sim.app.worker import State
from incident.sim.truth import Selector, Truth, TruthFault

CI_MIN = 6  # merge -> deploy
Marks = list[tuple[int, dict[str, Value]]]


def load_world(root: Path) -> tuple[AppWorld, repo.Tree]:
    world = AppWorld.model_validate_json((root / "world.json").read_text(encoding="utf-8"))
    return world, repo.load_tree(root / "repo")


def _at(recipe: AppRecipe, minute: float) -> datetime:
    return (recipe.start + timedelta(minutes=minute)).replace(microsecond=0)


def _routine(world: AppWorld, recipe: AppRecipe, rng: random.Random) -> list[AppChange]:
    """Harmless commits as background noise, kept clear of every real change and onset."""
    taken = [c.at_min for c in recipe.changes] + [e.at_min for e in recipe.externals]
    out: list[AppChange] = []
    for c in rng.sample(world.routine, k=min(3, len(world.routine))):
        for _ in range(30):
            t = rng.randrange(8, recipe.minutes - 5)
            if all(abs(t - o) >= 15 for o in taken):
                out.append(c.model_copy(update={"at_min": t, "id": f"routine-{c.id}"}))
                taken.append(t)
                break
    return out


def _ref(recipe: AppRecipe, c: AppChange) -> str:
    return repo.sha(recipe.id, c.id) if c.edits else f"ct-{repo.sha(recipe.id, c.id)}"


def _apply_changes(
    recipe: AppRecipe, tree: repo.Tree, changes: list[AppChange], rng: random.Random
) -> tuple[Marks, list[Change], list[CodeChange]]:
    marks: Marks = []
    feed: list[Change] = []
    code: list[CodeChange] = []
    for c in sorted(changes, key=lambda c: c.at_min):
        ts, ref = _at(recipe, c.at_min), _ref(recipe, c)
        changed: dict[str, Value] = {}
        if c.edits:
            new, diffs = repo.commit(tree, c)
            code.append(
                CodeChange(
                    ref=ref,
                    service=c.service,
                    title=c.title,
                    author=c.author,
                    pr=rng.randrange(140, 400),
                    merged_at=ts - timedelta(minutes=CI_MIN),
                    ci=c.ci,
                    files=diffs,
                )
            )
            if c.ci == "failure":
                continue  # merged, but the pipeline failed: nothing was deployed
            before, tree = repo.config_keys(tree), new
            changed = {k: v for k, v in repo.config_keys(tree).items() if before.get(k) != v}
        feed.append(Change(ts=ts, kind=c.kind, service=c.service, ref=ref, note=c.title))
        marks.append((c.at_min, {**changed, **c.set}))
    return marks, feed, code


def _states(world: AppWorld, recipe: AppRecipe, tree: repo.Tree, marks: Marks) -> list[State]:
    states = []
    for m in range(recipe.minutes + 1):
        s: State = {**world.runtime, **repo.config_keys(tree)}
        for at, patch in marks:
            if at <= m:
                s.update(patch)
        for e in recipe.externals:
            if e.at_min <= m < (e.until_min or 10**6):
                s.update(e.set)
        states.append(s)
    return states


def _conversations(sim: Sim, recipe: AppRecipe, states: list[State]) -> list[Conversation]:
    out = []
    for m in sim.msgs:
        o = m.out
        ran = [t for st, t, *_ in m.stages if st == "worker"]
        s = states[int(ran[-1])] if ran else None
        out.append(
            Conversation(
                id=m.job.id,
                user=m.job.user.id,
                received_at=_at(recipe, m.received),
                kind=m.job.kind,
                intent=m.job.intent,
                text=m.text,
                status=m.status,
                attempts=m.attempts,
                prompt_version=str(s["llm.prompt_version"]) if s else None,
                model=str(s["llm.model"]) if s else None,
                context=o.context if o else [],
                tool_calls=o.calls if o else [],
                answer=o.answer if o else None,
                delivery=m.delivery,
                feedback=m.feedback,
                stages=[
                    StageEvent(stage=st, ts=_at(recipe, t), ms=round(ms), ok=ok, detail=d)
                    for st, t, ms, ok, d in m.stages
                ],
            )
        )
    return out


def _deploy_logs(feed: list[Change]) -> list[LogLine]:
    return [
        LogLine(
            ts=c.ts + timedelta(seconds=40),
            service=c.service,
            host=f"{c.service}-1",
            level="INFO",
            msg=f"INIT_START runtime python:3.12 function version {c.ref}",
        )
        for c in feed
        if c.kind == "deploy"
    ]


def _drop(recipe: AppRecipe, data: Dataset) -> None:
    for d in recipe.drops:
        cut = _at(recipe, d.from_min)
        if d.logs:
            data.logs = [ln for ln in data.logs if ln.service != d.service or ln.ts < cut]
        if d.metrics and d.service in data.metrics:
            for vals in data.metrics[d.service].values():
                vals[d.from_min :] = [None] * (len(vals) - d.from_min)
        if d.traces:
            for c in data.conversations:
                if c.received_at >= cut:
                    c.stages, c.tool_calls, c.context = [], [], []


def _truth(recipe: AppRecipe, refs: dict[str, str], f: AppFault) -> TruthFault:
    times = {c.id: c.at_min for c in recipe.changes} | {e.id: e.at_min for e in recipe.externals}
    onset, end = _at(recipe, times[f.cause]), _at(recipe, recipe.minutes)
    sels = [
        Selector(
            kind=d.kind,
            service=d.service,
            level=d.level,
            contains=refs.get(f.cause, "") if d.kind == "change" else d.contains,
            metric=d.metric,
            min_value=d.min_value,
            failed_tool=d.failed_tool,
            start=onset,
            end=end,
        )
        for d in f.decisive
    ]
    t = f.truth
    return TruthFault(
        id=f.id,
        role=f.role,
        component=t.component,
        cause_type=t.cause_type,
        description=t.description,
        onset=onset,
        decisive=sels,
    )


def simulate_app(world: AppWorld, tree: repo.Tree, recipe: AppRecipe) -> tuple[Dataset, Truth]:
    rng = random.Random(recipe.seed)
    changes = recipe.changes + _routine(world, recipe, rng)
    marks, feed, code = _apply_changes(recipe, tree, changes, rng)
    states = _states(world, recipe, tree, marks)
    sim = run(world, recipe, states, rng)
    data = Dataset(
        incident=Incident(
            reported_at=_at(recipe, recipe.incident_at_min), text=recipe.incident_text
        ),
        start=recipe.start,
        minutes=recipe.minutes,
        topology=Topology(services=world.services, edges=world.edges, queues=world.queues),
        logs=sorted(
            telemetry.logs(sim, recipe.start, rng) + _deploy_logs(feed), key=lambda ln: ln.ts
        ),
        metrics=telemetry.metrics(sim, recipe.minutes),
        changes=feed,
        history=world.history + recipe.history_extra,
        tool_faults=recipe.tool_faults,
        conversations=_conversations(sim, recipe, states),
        code_changes=code,
    )
    _drop(recipe, data)
    refs = {c.id: _ref(recipe, c) for c in recipe.changes}
    truth = Truth(
        faults=[_truth(recipe, refs, f) for f in recipe.faults],
        answerable=recipe.answerable,
        expected_status=recipe.expected_status,
        trap=recipe.trap,
    )
    return data, truth
