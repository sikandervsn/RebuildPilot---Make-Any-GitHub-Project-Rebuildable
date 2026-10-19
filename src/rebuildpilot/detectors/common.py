"""Small detector helpers kept in one place."""

from __future__ import annotations

from ..models import Finding, Severity


def make_finding(
    rule_id: str,
    severity: Severity,
    title: str,
    explanation: str,
    remediation: str,
    file_path: str | None = None,
    line_number: int | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title=title,
        file_path=file_path,
        line_number=line_number,
        explanation=explanation,
        remediation=remediation,
    )
