"""Scenario files: what to plant, how to exercise it, how to erase it, and how to probe."""

from __future__ import annotations

import secrets
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ScenarioError(Exception):
    """A scenario could not be found, parsed or validated."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Subject(_Strict):
    name: str


class Fact(_Strict):
    statement: str
    canary: str | None = None
    plant_as: str
    sensitive_values: list[str] = Field(default_factory=list)


class Erasure(_Strict):
    request: str
    method: Literal["vendor-default", "strict"] = "vendor-default"


class BehaviourProbe(_Strict):
    question: str


class Probes(_Strict):
    recall: list[str] = Field(default_factory=list)
    behaviour: list[BehaviourProbe] = Field(default_factory=list)


class JudgeSpec(_Strict):
    question: str
    samples: int = Field(default=3, ge=1, le=10)


class Scenario(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: int = 1
    description: str
    subject: Subject
    fact: Fact
    exercise: list[str] = Field(min_length=1)
    erasure: Erasure
    probes: Probes
    judge: JudgeSpec

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        if self.fact.canary is not None and self.fact.canary not in self.fact.plant_as:
            raise ValueError("fact.canary must appear in fact.plant_as")
        if not self.probes.recall and not self.probes.behaviour:
            raise ValueError("at least one recall or behaviour probe is required")
        return self


def _builtin_dir() -> Traversable:
    return resources.files("erasewitness") / "builtin_scenarios"


def list_builtin() -> list[str]:
    return sorted(
        entry.name.removesuffix(".yaml")
        for entry in _builtin_dir().iterdir()
        if entry.name.endswith(".yaml")
    )


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "scenario"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def load_scenario(ref: str) -> Scenario:
    """Load a built-in scenario by name, or a scenario file by path."""
    path = Path(ref)
    if path.suffix in {".yaml", ".yml"}:
        if not path.is_file():
            raise ScenarioError(f"scenario file not found: {ref}")
        text = path.read_text(encoding="utf-8")
    else:
        entry = _builtin_dir() / f"{ref}.yaml"
        if not entry.is_file():
            known = ", ".join(list_builtin())
            raise ScenarioError(f"unknown scenario '{ref}' (built-in: {known})")
        text = entry.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScenarioError(f"invalid YAML in {ref}: {exc}") from exc
    if not isinstance(data, dict):
        raise ScenarioError(f"scenario {ref} must be a mapping")
    try:
        return Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioError(f"invalid scenario {ref}: {_format_errors(exc)}") from exc


def new_canary() -> str:
    """A unique marker. Always contains digits so digit-stripping rewrites remove it."""
    return f"EW-{secrets.randbelow(1_000_000):06d}"


def with_canary(scenario: Scenario, canary: str | None = None) -> Scenario:
    """Return the scenario with a canary set and embedded in plant_as."""
    if scenario.fact.canary is not None:
        return scenario
    marker = canary or new_canary()
    fact = scenario.fact.model_copy(
        update={"canary": marker, "plant_as": f"{scenario.fact.plant_as} (reference {marker})"}
    )
    return scenario.model_copy(update={"fact": fact})
