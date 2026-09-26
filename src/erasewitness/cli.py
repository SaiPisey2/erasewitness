"""Command-line interface."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from erasewitness.judges.base import SemanticJudge
from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.report import SecretLeakError, write_run
from erasewitness.runner import Event, RunConfig, Runner
from erasewitness.scenario import Scenario, ScenarioError, list_builtin, load_scenario
from erasewitness.signing import (
    DEFAULT_KEY_PATH,
    fingerprint,
    generate_key,
    load_or_create_key,
    verify_run,
)
from erasewitness.store import RunIndex
from erasewitness.targets import TARGETS
from erasewitness.types import RunResult, Verdict

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Prove whether an AI agent's memory really forgot.",
)
scenarios_app = typer.Typer(no_args_is_help=True, help="Built-in scenarios.")
app.add_typer(scenarios_app, name="scenarios")

JUDGES: dict[str, Callable[[], SemanticJudge]] = {"overlap": OverlapJudge}
EXIT_CODES = {RunResult.PASS: 0, RunResult.FAIL: 1, RunResult.INCONCLUSIVE: 2, RunResult.ERROR: 3}


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(3)


def _print_event(event: Event) -> None:
    if event.kind == "step":
        typer.echo(f"[{event.step}]", err=True)


def _load(scenario: str) -> Scenario:
    try:
        return load_scenario(scenario)
    except ScenarioError as exc:
        _fail(str(exc))


@app.command()
def run(
    target: Annotated[str, typer.Option(help="Target name, e.g. reference-leaky.")],
    scenario: Annotated[str, typer.Option(help="Built-in scenario name or YAML file path.")],
    judges: Annotated[str, typer.Option(help="Comma-separated semantic judges.")] = "overlap",
    strict: Annotated[
        bool, typer.Option(help="Also delete everything the snapshot flagged.")
    ] = False,
    out: Annotated[Path, typer.Option(help="Directory for run folders.")] = Path(
        ".erasewitness/runs"
    ),
    key: Annotated[Path, typer.Option(help="ed25519 signing key.")] = DEFAULT_KEY_PATH,
    redact_evidence: Annotated[
        bool, typer.Option(help="Store hashes instead of evidence text.")
    ] = False,
) -> None:
    """Plant a fact, erase it, probe every layer and write a signed report."""
    loaded = _load(scenario)
    if target not in TARGETS:
        _fail(f"unknown target '{target}' (known: {', '.join(sorted(TARGETS))})")
    names = [n.strip() for n in judges.split(",") if n.strip()]
    unknown = [n for n in names if n not in JUDGES]
    if unknown or not names:
        _fail(f"unknown judge '{','.join(unknown)}' (known: {', '.join(sorted(JUDGES))})")
    if "overlap" in names:
        typer.echo(
            "warning: the overlap judge is an offline heuristic; results are not evidence",
            err=True,
        )

    runner = Runner(
        TARGETS[target],
        Panel([JUDGES[n]() for n in names]),
        RunConfig(strict=strict),
        on_event=_print_event,
    )
    outcome = runner.run(loaded)

    try:
        signing_key, created = load_or_create_key(key)
    except (OSError, ValueError) as exc:
        _fail(f"cannot load signing key {key}: {exc}")
    if created:
        typer.echo(f"created signing key {key}", err=True)
    try:
        run_dir = write_run(outcome, out, signing_key, redact=redact_evidence)
    except SecretLeakError as exc:
        _fail(str(exc))
    except (OSError, ValueError) as exc:
        _fail(f"cannot write report: {exc}")

    leaked = sum(p.verdict is Verdict.LEAKED for p in outcome.probes)
    typer.echo(
        f"{outcome.result.value}: {leaked} of {len(outcome.probes)} probes leaked after erasure"
    )
    if outcome.error:
        typer.echo(f"run error: {outcome.error}", err=True)
    typer.echo(f"report: {run_dir / 'report.html'}")
    typer.echo(f"signer: {fingerprint(signing_key.public_key())}")
    try:
        RunIndex(out.parent / "index.sqlite").add(outcome, run_dir)
    except (OSError, sqlite3.Error) as exc:
        _fail(f"report written but run index update failed: {exc}")
    raise typer.Exit(EXIT_CODES[outcome.result])


@app.command()
def verify(
    run_dir: Annotated[Path, typer.Argument(help="Run folder to verify.")],
    expect: Annotated[
        str | None, typer.Option(help="Expected signer fingerprint to pin against.")
    ] = None,
) -> None:
    """Check a run folder's hashes and signature."""
    result = verify_run(run_dir, expect)
    if result.ok:
        typer.echo(
            f"OK: signature and {result.files_checked} file hashes verified; "
            f"signer {result.fingerprint}"
        )
        if not result.pinned:
            typer.echo(
                "warning: signer not pinned; pass --expect <fingerprint> to confirm who signed it"
            )
        return
    for problem in result.problems:
        typer.echo(f"problem: {problem}")
    raise typer.Exit(1)


@app.command()
def keygen(
    key: Annotated[Path, typer.Option(help="Where to write the key.")] = DEFAULT_KEY_PATH,
    force: Annotated[bool, typer.Option(help="Replace an existing key.")] = False,
) -> None:
    """Create the ed25519 key used to sign reports."""
    try:
        private = generate_key(key, force=force)
    except FileExistsError:
        typer.echo(f"error: {key} already exists; use --force to replace it", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"key written to {key}")
    typer.echo(f"fingerprint {fingerprint(private.public_key())}")


@scenarios_app.command("list")
def scenarios_list() -> None:
    """List built-in scenarios."""
    for name in list_builtin():
        typer.echo(f"{name:18} {load_scenario(name).description}")
