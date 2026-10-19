"""JSON report rendering."""

from __future__ import annotations

import json

from ..models import AnalysisReport, RemediationPlan, ValidationReport


def render(report: AnalysisReport | ValidationReport | RemediationPlan) -> str:
    """Render stable, indented JSON suitable for a file or a pipe."""

    return json.dumps(report.as_json_dict(), indent=2, sort_keys=True) + "\n"
