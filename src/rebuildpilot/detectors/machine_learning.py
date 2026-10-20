"""Reproducibility checks for computer-vision and machine-learning projects."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, ProjectFile, Severity
from .common import make_finding
from .context import ScanContext


FRAMEWORK_IMPORTS = {
    "OpenCV": re.compile(r"(?m)^\s*(?:import\s+cv2\b|from\s+cv2\b)"),
    "scikit-learn": re.compile(r"(?m)^\s*(?:import\s+sklearn\b|from\s+sklearn\b)"),
    "Random Forest": re.compile(r"(?m)\b(?:RandomForestClassifier|RandomForestRegressor)\b"),
    "NumPy": re.compile(r"(?m)^\s*(?:import\s+numpy\b|from\s+numpy\b)"),
    "pandas": re.compile(r"(?m)^\s*(?:import\s+pandas\b|from\s+pandas\b)"),
    "PyTorch": re.compile(r"(?m)^\s*(?:import\s+torch\b|from\s+torch\b)"),
    "TensorFlow": re.compile(r"(?m)^\s*(?:import\s+tensorflow\b|from\s+tensorflow\b)"),
    "Joblib": re.compile(r"(?m)^\s*(?:import\s+joblib\b|from\s+joblib\b)"),
}
MODEL_SUFFIXES = {".pkl", ".pickle", ".joblib", ".onnx", ".h5", ".keras", ".pt", ".pth", ".sav"}
DATA_SUFFIXES = {".csv", ".parquet", ".feather", ".npy", ".npz", ".pkl", ".pickle"}
ENTRYPOINT_NAMES = {"train.py", "predict.py", "inference.py", "infer.py", "recognize.py", "app.py", "main.py"}
SEED_RE = re.compile(r"\b(?:random_state|random_seed|manual_seed|set_seed|seed)\b", re.IGNORECASE)
MODEL_LOAD_RE = re.compile(r"\b(?:joblib\.load|pickle\.load|load_model|torch\.load|onnxruntime)\b")


class MachineLearningResult(BaseModel):
    frameworks: list[str]
    model_artifacts: list[str]
    dataset_artifacts: list[str]
    entrypoints: list[str]
    findings: list[Finding]


def _package_text(context: ScanContext) -> str:
    return "\n".join(
        item.text or ""
        for item in context.files
        if Path(item.relative_path).name.lower()
        in {"requirements.txt", "requirements.lock", "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock"}
    ).lower()


def detect(context: ScanContext) -> MachineLearningResult:
    source_files = [
        item
        for item in context.text_files()
        if Path(item.relative_path).suffix.lower() in {".py", ".ipynb", ".js", ".ts"}
    ]
    source_text = "\n".join(item.text or "" for item in source_files)
    frameworks = sorted(name for name, pattern in FRAMEWORK_IMPORTS.items() if pattern.search(source_text))
    model_artifacts = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).suffix.lower() in MODEL_SUFFIXES
    )
    dataset_artifacts = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).suffix.lower() in DATA_SUFFIXES
        and Path(item.relative_path).suffix.lower() not in MODEL_SUFFIXES
    )
    entrypoints = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).name.lower() in ENTRYPOINT_NAMES
    )
    findings: list[Finding] = []
    if not frameworks:
        return MachineLearningResult(
            frameworks=[],
            model_artifacts=model_artifacts,
            dataset_artifacts=dataset_artifacts,
            entrypoints=entrypoints,
            findings=[],
        )

    findings.append(
        make_finding(
            "RP-ML-001",
            Severity.info,
            "Machine-learning workflow detected",
            f"Detected {', '.join(frameworks)} in source code.",
            "Pin the runtime and ML dependencies, document setup and inference/training commands, and verify the workflow from a clean clone.",
        )
    )
    package_text = _package_text(context)
    expected_packages = {
        "OpenCV": ("opencv-python", "opencv-contrib-python"),
        "scikit-learn": ("scikit-learn", "sklearn"),
        "Random Forest": ("scikit-learn", "sklearn"),
        "NumPy": ("numpy",),
        "pandas": ("pandas",),
        "PyTorch": ("torch",),
        "TensorFlow": ("tensorflow",),
        "Joblib": ("joblib",),
    }
    missing = [
        framework
        for framework in frameworks
        if not any(package in package_text for package in expected_packages.get(framework, ()))
    ]
    if missing:
        findings.append(
            make_finding(
                "RP-ML-002",
                Severity.high,
                "ML imports are not represented in dependency metadata",
                f"Source imports {', '.join(missing)}, but the recognized dependency files do not declare the matching packages.",
                "Declare every runtime ML package in the project manifest and commit the lockfile used to install it.",
            )
        )
    if model_artifacts:
        findings.append(
            make_finding(
                "RP-ML-003",
                Severity.medium,
                "Serialized model artifact detected",
                f"Detected model artifact(s): {', '.join(model_artifacts)}.",
                "Document the model format, training data/version, library versions, preprocessing steps, and a checksum or model-generation command.",
            )
        )
    if MODEL_LOAD_RE.search(source_text) and not model_artifacts:
        findings.append(
            make_finding(
                "RP-ML-004",
                Severity.high,
                "Model is loaded from an external or undocumented path",
                "The code loads a serialized model, but no model artifact is present in the repository inventory.",
                "Document how to obtain or generate the model and make the path configurable through a relative path or environment variable.",
            )
        )
    if any(name in frameworks for name in ("scikit-learn", "Random Forest")) and not SEED_RE.search(source_text):
        findings.append(
            make_finding(
                "RP-ML-005",
                Severity.medium,
                "No deterministic random seed was detected",
                "The project uses scikit-learn or a random-forest workflow, but no random_state or seed configuration was detected.",
                "Set and document a seed for data splitting, model training, and any preprocessing that uses randomness.",
            )
        )
    if not entrypoints:
        findings.append(
            make_finding(
                "RP-ML-006",
                Severity.medium,
                "ML entry point was not detected",
                "ML dependencies are present, but no conventional training, inference, prediction, or application entry point was found.",
                "Document exact training and inference commands in the README and expose them through a script or Make target.",
            )
        )
    if not dataset_artifacts and not any("dataset" in (item.text or "").lower() for item in context.text_files()):
        findings.append(
            make_finding(
                "RP-ML-007",
                Severity.medium,
                "Training data provenance is not documented",
                "No dataset artifact or dataset documentation was detected in the repository.",
                "Document the dataset source, version, expected layout, preprocessing, and how a clean environment obtains it without committing sensitive data.",
            )
        )
    return MachineLearningResult(
        frameworks=frameworks,
        model_artifacts=model_artifacts,
        dataset_artifacts=dataset_artifacts,
        entrypoints=entrypoints,
        findings=findings,
    )
