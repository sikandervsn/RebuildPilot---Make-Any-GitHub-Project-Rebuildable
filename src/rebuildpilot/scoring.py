"""Explainable scoring for deterministic findings."""

from __future__ import annotations

from collections.abc import Iterable

from .models import Finding, ScoreReason, Severity


DEFAULT_DEDUCTIONS: dict[Severity, int] = {
    Severity.critical: 25,
    Severity.high: 15,
    Severity.medium: 8,
    Severity.low: 3,
    Severity.info: 0,
}


def with_default_deductions(findings: Iterable[Finding]) -> list[Finding]:
    """Fill omitted deductions from the stable severity policy."""

    return [
        finding.model_copy(update={"score_deduction": finding.score_deduction or DEFAULT_DEDUCTIONS[finding.severity]})
        for finding in findings
    ]


def calculate_score(findings: Iterable[Finding]) -> tuple[int, list[ScoreReason]]:
    """Return a 0-100 score and the exact deductions used to calculate it."""

    normalized = with_default_deductions(findings)
    reasons = [
        ScoreReason(
            rule_id=finding.rule_id,
            points=finding.score_deduction,
            explanation=f"{finding.title} ({finding.severity.value})",
        )
        for finding in normalized
        if finding.score_deduction > 0
    ]
    score = max(0, 100 - sum(reason.points for reason in reasons))
    return score, reasons
