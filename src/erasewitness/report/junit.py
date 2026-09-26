"""JUnit XML so CI systems can gate on erasure results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def render_junit(data: dict[str, Any]) -> str:
    probes = data["probes"]
    suite = ET.Element(
        "testsuite",
        name="erasewitness",
        tests=str(len(probes)),
        failures=str(sum(p["verdict"] == "LEAKED" for p in probes)),
        skipped=str(sum(p["verdict"] in ("UNCERTAIN", "INVALID") for p in probes)),
    )
    classname = f"{data['target']}.{data['scenario']['id']}"
    for probe in probes:
        case = ET.SubElement(suite, "testcase", classname=classname, name=probe["probe_id"])
        if probe["verdict"] == "LEAKED":
            ET.SubElement(case, "failure", message=probe["reason"])
        elif probe["verdict"] in ("UNCERTAIN", "INVALID"):
            ET.SubElement(case, "skipped", message=f"{probe['verdict']}: {probe['reason']}")
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
