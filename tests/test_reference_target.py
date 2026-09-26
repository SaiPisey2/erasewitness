import pytest

from erasewitness.scenario import Scenario
from erasewitness.targets import TARGETS, create_target
from erasewitness.targets.reference import ReferenceTarget
from erasewitness.types import Item, Layer


def _prepared(mode: str, salary: Scenario, **kw: bool) -> ReferenceTarget:
    target = ReferenceTarget(mode, **kw)  # type: ignore[arg-type]
    target.setup("run-1")
    target.plant(salary.fact.plant_as)
    target.exercise(salary.exercise)
    return target


def test_registry_names() -> None:
    assert sorted(TARGETS) == ["reference-clean", "reference-leaky", "reference-overdelete"]
    assert create_target("reference-leaky").name == "reference-leaky"
    with pytest.raises(KeyError):
        create_target("nope")


def test_plant_and_probe_store(salary: Scenario) -> None:
    target = _prepared("clean", salary)
    assert [i.source for i in target.probe_store("SALARY")] == ["memory:m1"]
    assert target.probe_store("income") == []


def test_summary_is_reworded_without_digits(salary: Scenario) -> None:
    target = _prepared("clean", salary)
    summary = [i for i in target.probe_derived() if i.source == "summary"][0]
    assert "salary" in summary.text
    assert "42" not in summary.text
    assert "EW-004211" not in summary.text


def test_clean_erase_removes_everything(salary: Scenario) -> None:
    target = _prepared("clean", salary)
    assert target.erase(salary, None).ok
    assert target.probe_store("salary") == []
    assert target.probe_derived() == []
    assert target.ask("anything") == "I don't have that information."


def test_leaky_erase_keeps_history_and_summary(salary: Scenario) -> None:
    target = _prepared("leaky", salary)
    target.erase(salary, None)
    assert target.probe_store("salary") == []
    assert [i.source for i in target.probe_derived()] == ["history:m1", "summary"]


def test_leaky_strict_items_are_deleted(salary: Scenario) -> None:
    target = _prepared("leaky", salary)
    strict = [
        Item(Layer.DERIVED, "history:m1", ""),
        Item(Layer.DERIVED, "summary", ""),
    ]
    target.erase(salary, strict)
    assert target.probe_derived() == []


def test_overdelete_removes_unrelated_memory(salary: Scenario) -> None:
    target = _prepared("overdelete", salary)
    assert "dark mode" in target.ask("x")
    target.erase(salary, None)
    assert target.snapshot() == []


def test_settle_and_failure_switches(salary: Scenario) -> None:
    target = _prepared("clean", salary, settle_ok=False, fail_erase=True)
    assert target.settle(1.0) is False
    with pytest.raises(RuntimeError):
        target.erase(salary, None)


def test_recorded_edges_and_cleanup(salary: Scenario) -> None:
    target = _prepared("clean", salary)
    assert [(e.src, e.dst) for e in target.recorded_edges()] == [("memory:m1", "history:m1")]
    assert target.cleanup() == []
    assert target.snapshot() == []
