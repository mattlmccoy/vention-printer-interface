"""Dot-array bias interpretation in ``recommend_compensation_overall``.

Regression guard for a latent ``NameError``: the dot-array diagnostics block
referenced an undefined ``spacing_scale_used`` inside the branch guarded by
finite ``diameter_error_pct`` + ``scale_xy_from_diameter``. Any real dot-array
metrology with those two fields finite crashed report generation.

The boolean's intent (see the surrounding "Scaling philosophy" comments) is:
did we have a usable dot-spacing-derived motion scale? If so, diameter error is
interpreted as deposition morphology; if not, advise preferring dot spacing.
These tests lock both branches and prove the crash cannot return.
"""

from __future__ import annotations

from vention_printer_interface.analysis.feature_analysis import (
    recommend_compensation_overall,
)


def _report_for_dot(dot: dict[str, float]) -> str:
    return recommend_compensation_overall([("dot", dot)])


def test_dot_bias_with_spacing_available_reads_as_morphology() -> None:
    """Finite spacing + finite diameter error: interpret as deposition morphology."""
    dot = {
        # dot-spacing motion scale IS available (finite spacing errors)
        "spacing_x_error_pct": 0.05,
        "spacing_y_error_pct": -0.03,
        # dot-diameter diagnostic signal
        "diameter_error_pct": -1.20,
        "scale_xy_from_diameter": 1.012146,
    }

    report = _report_for_dot(dot)  # must not raise NameError

    assert "Dot size bias (diameter error):" in report
    assert "dot spacing calibrates the motion frame" in report
    # spacing-available branch, NOT the fallback advice
    assert "Prefer dot spacing for motion scale when available." not in report


def test_dot_bias_large_but_finite_spacing_still_reads_as_morphology() -> None:
    """Gate is availability, not calibration-quality.

    Spacing errors are large (far outside the 0.20% action threshold) but finite,
    so a dot-spacing motion scale WAS measured. The report must still route to the
    morphology interpretation, not the "prefer dot spacing when available" advice.
    This assertion fails under threshold-based gating and passes under the correct
    availability-based gating, pinning the intended semantics.
    """
    dot = {
        # measured but far off (>> 0.20% threshold) -> still "available"
        "spacing_x_error_pct": 1.50,
        "spacing_y_error_pct": -1.20,
        "diameter_error_pct": -1.20,
        "scale_xy_from_diameter": 1.012146,
    }

    report = _report_for_dot(dot)

    assert "dot spacing calibrates the motion frame" in report
    assert "Prefer dot spacing for motion scale when available." not in report


def test_dot_bias_without_spacing_advises_prefer_spacing() -> None:
    """No dot-spacing signal: advise preferring dot spacing for motion scale."""
    dot = {
        # no spacing_x_error_pct / spacing_y_error_pct -> spacing scale unavailable
        "diameter_error_pct": 2.50,
        "scale_xy_from_diameter": 0.975610,
    }

    report = _report_for_dot(dot)  # must not raise NameError

    assert "Dot size bias (diameter error):" in report
    assert "Prefer dot spacing for motion scale when available." in report
    assert "dot spacing calibrates the motion frame" not in report
