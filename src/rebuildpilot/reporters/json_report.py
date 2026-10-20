"""JSON report rendering."""

from __future__ import annotations

import json
from typing import Any

from ..models import AnalysisReport, RemediationPlan, ValidationReport


def render(report: AnalysisReport | ValidationReport | RemediationPlan) -> str:
    """Render stable, indented JSON suitable for a file or a pipe."""

    return render_payload(report.as_json_dict())


def render_payload(payload: dict[str, Any]) -> str:
    """Render an already-serialized report payload as stable JSON."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
