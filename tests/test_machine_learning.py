from pathlib import Path

from rebuildpilot.scanner import analyze


def test_detects_ml_stack_and_reproducibility_gaps(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("opencv-python\nscikit-learn\n", encoding="utf-8")
    (tmp_path / "vision.py").write_text(
        "import cv2\n"
        "from sklearn.ensemble import RandomForestClassifier\n"
        "import joblib\n"
        "model = joblib.load('model.joblib')\n",
        encoding="utf-8",
    )
    (tmp_path / "model.joblib").write_bytes(b"model")

    report = analyze(tmp_path)

    assert "OpenCV" in report.ml_frameworks
    assert "scikit-learn" in report.ml_frameworks
    assert report.model_artifacts == ["model.joblib"]
    rule_ids = {finding.rule_id for finding in report.findings}
    assert "RP-ML-003" in rule_ids
    assert "RP-ML-005" in rule_ids


def test_reports_missing_ml_dependency_metadata(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import cv2\nfrom sklearn.ensemble import RandomForestClassifier\n", encoding="utf-8")

    report = analyze(tmp_path)

    assert "RP-ML-002" in {finding.rule_id for finding in report.findings}
