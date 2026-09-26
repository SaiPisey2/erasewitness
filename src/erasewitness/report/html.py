"""Renders the self-contained HTML report."""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, PackageLoader

from erasewitness.report.data import evidence_name

_ENV = Environment(loader=PackageLoader("erasewitness.report", "templates"), autoescape=True)


def _leak_cards(data: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for probe in data["probes"]:
        if probe["verdict"] != "LEAKED":
            continue
        for item in evidence[evidence_name(probe["probe_id"])]["after"]:
            if item["verdict"] == "LEAKED":
                cards.append({"probe_id": probe["probe_id"], **item})
    return cards


def render_html(data: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> str:
    template = _ENV.get_template("report.html.j2")
    return template.render(r=data, leaks=_leak_cards(data, evidence))
