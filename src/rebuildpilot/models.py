"""Typed data models shared by scanners, detectors, and report writers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """Impact level for a reproducibility finding."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class ReportFormat(StrEnum):
    markdown = "markdown"
    json = "json"
    html = "html"


class CheckStatus(StrEnum):
    """Outcome of an executable validation check."""

    passed = "passed"
    failed = "failed"
    skipped = "skipped"


class ProjectFile(BaseModel):
    """One file in the inspected project and its safely decoded contents."""

    model_config = ConfigDict(frozen=True)

    relative_path: str
    absolute_path: str
    text: str | None = None
    unreadable: bool = False
    read_error: str | None = None


class Finding(BaseModel):
    """A deterministic, actionable scanner result."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    title: str
    file_path: str | None = None
    line_number: int | None = Field(default=None, ge=1)
    explanation: str
    remediation: str
    score_deduction: int = Field(default=0, ge=0, le=100)


class ScoreReason(BaseModel):
    rule_id: str
    points: int = Field(ge=0, le=100)
    explanation: str


class AnalysisReport(BaseModel):
    """Complete serializable result of analyzing one project."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    project_type: str
    languages: list[str]
    dependency_manifests: list[str]
    dependency_lockfiles: list[str]
    runtime_files: list[str]
    environment_files: list[str]
    runtime_definitions: list[str]
    test_configuration: list[str]
    likely_test_commands: list[str]
    git_repository: bool
    environment_variables_used: list[str]
    environment_variables_documented: list[str]
    unreadable_files: list[str]
    findings: list[Finding]
    score: int = Field(ge=0, le=100)
    score_reasons: list[ScoreReason]
    summary: str
    ml_frameworks: list[str] = Field(default_factory=list)
    model_artifacts: list[str] = Field(default_factory=list)
    dataset_artifacts: list[str] = Field(default_factory=list)
    ml_entrypoints: list[str] = Field(default_factory=list)

    def critical_findings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.critical]

    def counts_by_severity(self) -> dict[str, int]:
        return {severity.value: sum(f.severity is severity for f in self.findings) for severity in Severity}

    def as_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ValidationCheck(BaseModel):
    """One static or executable validation result."""

    name: str
    status: CheckStatus
    command: str | None = None
    exit_code: int | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    details: str


class ValidationReport(BaseModel):
    """Analysis plus the safe, local checks requested by ``validate``."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    analysis: AnalysisReport
    checks: list[ValidationCheck]
    passed: bool
    summary: str

    def as_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class RemediationItem(BaseModel):
    """A recommendation produced without changing the inspected project."""

    priority: int = Field(ge=1)
    rule_id: str
    severity: Severity
    title: str
    file_path: str | None = None
    recommendation: str
    plan_only: bool = True


class RemediationPlan(BaseModel):
    """Safe, explainable remediation plan; it never contains file mutations."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    analysis: AnalysisReport
    items: list[RemediationItem]
    summary: str

    def as_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
