"""Static contracts for the Sales visual motion layer."""
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "frontend" / "sales.css").read_text(encoding="utf-8")


def test_wokker_palette_remains_the_source_of_truth():
    assert "--red:#c92c35" in CSS
    assert "--red-dark:#ab1d28" in CSS
    assert "outline: 3px solid var(--red)" in CSS


def test_animated_dashboard_and_navigation():
    assert "@keyframes sales-enter" in CSS
    assert ".content > .kpi-grid" in CSS
    assert ".content > .charts-row" in CSS
    assert ".nav-link:not(.active):hover" in CSS
    assert ".pi-bar-fill" in CSS
    assert ".modal-overlay.active .modal" in CSS


def test_reduced_motion_is_respected():
    assert "@media (prefers-reduced-motion: no-preference)" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "animation: none !important" in CSS
    assert "transition: none !important" in CSS


def test_motion_does_not_modify_backend_or_data_contracts():
    assert "sales-bar-reveal" in CSS
    assert "transform: scaleX(0)" in CSS
