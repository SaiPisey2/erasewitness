"""JUnit XML so CI systems can gate on erasure results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def render_junit(data: dict[str, Any]) -> str:
    probes = data["probes"]
    result = data["result"]
    run_is_error = result == "ERROR"
    run_is_inconclusive = result == "INCONCLUSIVE"
    tests = len(probes) + (1 if run_is_error or run_is_inconclusive else 0)
    failures = sum(p["verdict"] == "LEAKED" for p in probes) + (1 if run_is_inconclusive else 0)
    errors = 1 if run_is_error else 0
    suite = ET.Element(
        "testsuite",
        name="erasewitness",
        tests=str(tests),
        failures=str(failures),
        errors=str(errors),
        skipped=str(sum(p["verdict"] in ("UNCERTAIN", "INVALID") for p in probes)),
    )
    classname = f"{data['target']}.{data['scenario']['id']}"
    for probe in probes:
        case = ET.SubElement(suite, "testcase", classname=classname, name=probe["probe_id"])
        if probe["verdict"] == "LEAKED":
            ET.SubElement(case, "failure", message=probe["reason"])
        elif probe["verdict"] in ("UNCERTAIN", "INVALID"):
            ET.SubElement(case, "skipped", message=f"{probe['verdict']}: {probe['reason']}")
    if run_is_error:
        case = ET.SubElement(suite, "testcase", classname=classname, name="run")
        ET.SubElement(case, "error", message=data["error"] or "run error")
    elif run_is_inconclusive:
        case = ET.SubElement(suite, "testcase", classname=classname, name="run")
        findings = data["findings"]
        message = "; ".join(findings) if findings else "no probe could be confirmed"
        ET.SubElement(case, "failure", message=f"inconclusive: {message}")
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
