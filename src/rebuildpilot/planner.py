"""Non-mutating remediation planning built from analyzer findings."""

from __future__ import annotations

from pathlib import Path

from .models import RemediationItem, RemediationPlan, Severity
from .scanner import analyze


def plan(target: Path) -> RemediationPlan:
    """Create an ordered plan without writing to the target project."""

    analysis = analyze(target)
    actionable = [finding for finding in analysis.findings if finding.severity is not Severity.info]
    items = [
        RemediationItem(
            priority=index,
            rule_id=finding.rule_id,
            severity=finding.severity,
            title=finding.title,
            file_path=finding.file_path,
            recommendation=finding.remediation,
        )
        for index, finding in enumerate(actionable, start=1)
    ]
    if items:
        summary = f"{len(items)} plan-only remediation step(s) ordered by finding severity."
    else:
        summary = "No actionable findings were detected; no project changes are proposed."
    return RemediationPlan(
        target_path=analysis.target_path,
        analysis=analysis,
        items=items,
        summary=summary,
    )
