import pytest

from eval import judge


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(judge, "CACHE", tmp_path / "cache.jsonl")
    seen: list[str] = []
    return seen


def _stub(monkeypatch: pytest.MonkeyPatch, seen: list[str], answers: list[bool]) -> None:
    it = iter(answers)

    async def vote(prompt: str) -> bool:
        seen.append(prompt)
        return next(it)

    monkeypatch.setattr(judge, "_vote", vote)


async def test_the_judge_actually_receives_the_true_description(monkeypatch, isolated) -> None:  # type: ignore[no-untyped-def]  # covers: R16
    _stub(monkeypatch, isolated, [True, True, True])
    ok = await judge.same_cause("svc", "label_x", "svc", "c", "stmt", True, "THE REAL MECHANISM")
    assert ok and all("TRUE description: THE REAL MECHANISM" in p for p in isolated)


async def test_majority_of_three_decides_and_is_cached(monkeypatch, isolated) -> None:  # type: ignore[no-untyped-def]  # covers: R16
    _stub(monkeypatch, isolated, [True, False, True])
    assert await judge.same_cause("a", "l", "a", "c", "s", True, "d") is True
    assert len(isolated) == 3
    assert await judge.same_cause("a", "l", "a", "c", "s", True, "d") is True  # cache hit
    assert len(isolated) == 3
    _stub(monkeypatch, isolated, [False, False, True])
    assert await judge.same_cause("a", "l", "a", "c", "other", True, "d") is False


async def test_a_wrong_component_never_reaches_the_model(monkeypatch, isolated) -> None:  # type: ignore[no-untyped-def]  # covers: R16
    _stub(monkeypatch, isolated, [])
    assert await judge.same_cause("svc-a", "l", "svc-b", "c", "s", True, "d") is False
    assert isolated == []
    assert (
        await judge.same_cause("svc-a", "l", "SVC-A", "c", "s", False, "d") is True
    )  # offline mode


def test_rubric_asks_for_reasoning_before_the_verdict() -> None:  # covers: R16
    assert judge.RUBRIC.index('"why"') < judge.RUBRIC.index('"same"')
