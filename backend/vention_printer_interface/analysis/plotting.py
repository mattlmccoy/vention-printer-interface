"""Publication-quality figure export (seaborn/matplotlib) — optional ``plots`` extra.

Every heavy import is lazy so importing this module never fails when the extra is
absent; ``plots_available()`` is the guard the API uses to 404 gracefully. Each
``render_*`` returns raw PNG or PDF bytes via matplotlib's headless Agg backend, so
the export endpoints stream a download without ever touching the filesystem.

Install with ``uv sync --extra plots``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib.util import find_spec
from io import BytesIO
from typing import Any

# The only two download formats we serve. PNG for quick viewing, PDF (vector) for
# dropping into reports/papers.
FORMAT_CONTENT_TYPE: dict[str, str] = {"png": "image/png", "pdf": "application/pdf"}

# House palette — mirrors the frontend SVG plots (accent gold, ok-green band).
_ACCENT = "#d9a441"
_OK = "#2e7d32"
_INK = "#222222"
_MUTED = "#999999"


def plots_available() -> bool:
    """True when the optional ``plots`` extra (matplotlib/seaborn/pandas) is importable."""
    return all(find_spec(mod) is not None for mod in ("matplotlib", "seaborn", "pandas"))


def _new_axes(figsize: tuple[float, float] = (6.4, 3.6)) -> tuple[Any, Any, Any]:
    """Create a themed headless figure. Returns ``(pyplot, fig, ax)``."""
    import matplotlib

    matplotlib.use("Agg")  # headless: no display, safe on the operator/server
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid", context="notebook")
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    return plt, fig, ax


def _fig_bytes(plt: Any, fig: Any, fmt: str) -> bytes:
    """Serialize ``fig`` to raw bytes in ``fmt`` and close it."""
    if fmt not in FORMAT_CONTENT_TYPE:
        raise ValueError(f"unsupported format {fmt!r} (one of {sorted(FORMAT_CONTENT_TYPE)})")
    buf = BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


@dataclass(frozen=True)
class _Level:
    value: float
    count: int


def _bin_levels(reps: list[Any], quantum_mm: float = 0.1) -> list[_Level]:
    """Group reps by nearest encoder level (``quantum_mm``) and count each — quantised reps read as
    per-level counts instead of an overplotted blob. Ascending by level."""
    counts = Counter(round(round(float(r) / quantum_mm) * quantum_mm, 6) for r in reps)
    return [_Level(value, n) for value, n in sorted(counts.items())]


def render_backlash(
    positions: list[dict[str, Any]],
    recommended: float | None,
    tol_mm: float = 0.1,
    fmt: str = "png",
) -> bytes:
    """Backlash-per-depth COUNT-BUBBLE plot against a factory-style tolerance band.

    ``positions`` is the backlash-cal snapshot shape: each item has ``ref_mm`` (probed depth)
    and ``reps_mm`` (per-repeat measured lash). The measurement is quantised to the 0.1 mm
    encoder readout, so a raw strip plot stacks reps into an unreadable blob; instead each depth
    shows one bubble per observed level (area ∝ rep count, the count printed in it) plus a bold
    median tick. The shaded band is ±``tol_mm`` (one count); ``recommended`` is named in the title
    rather than drawn as a line (it usually equals the band edge). Mirrors ``BacklashPlot.tsx``.
    """
    plt, fig, ax = _new_axes()
    ax.axhspan(-tol_mm, tol_mm, color=_OK, alpha=0.12, zorder=0, label=f"±{tol_mm:g} mm (1 count)")
    ax.axhline(0.0, color=_MUTED, lw=1.0, zorder=1)

    all_counts = [lvl.count for p in positions for lvl in _bin_levels(p.get("reps_mm", []))]
    max_count = max(all_counts) if all_counts else 1
    if positions:
        for i, p in enumerate(positions):
            for lvl in _bin_levels(p.get("reps_mm", [])):
                ax.scatter([i], [lvl.value], s=140 + 900 * (lvl.count / max_count),
                           color=_ACCENT, alpha=0.85, edgecolors="none", zorder=3)
                ax.annotate(str(lvl.count), (i, lvl.value), ha="center", va="center",
                            fontsize=8, fontweight="bold", color="#10151f", zorder=4)
            med = _opt_float(p.get("backlash_median_mm"))
            if med is not None:
                ax.plot([i - 0.25, i + 0.25], [med, med], color=_INK, lw=2.5, zorder=5)
        ax.set_xticks(range(len(positions)),
                      labels=[f"{float(p['ref_mm']):g}" for p in positions])
        ax.set_xlim(-0.6, len(positions) - 0.4)
        span = max([tol_mm] + [abs(lvl.value) for p in positions
                               for lvl in _bin_levels(p.get("reps_mm", []))]) + 0.035
        ax.set_ylim(-span, span)  # margin so edge bubbles aren't clipped
    else:
        ax.text(0.5, 0.5, "no measurements yet", ha="center", va="center",
                transform=ax.transAxes, color=_MUTED)

    rec_txt = f" · recommended {recommended:g} mm" if recommended else ""
    ax.set_xlabel("probed depth (mm)")
    ax.set_ylabel("measured backlash (mm)")
    ax.set_title(f"Piston backlash per depth (bubble = rep count){rec_txt}")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    return _fig_bytes(plt, fig, fmt)


def _opt_float(v: Any) -> float | None:
    """Parse a CSV/JSON cell to float, treating ``None``/``""`` as unknown (not 0)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def render_layer_accuracy(
    rows: list[dict[str, Any]],
    tol_mm: float = 0.1,
    fmt: str = "png",
) -> bytes:
    """Cumulative build height: commanded vs actual per layer, with a ±``tol_mm`` band.

    ``rows`` is ``layer_accuracy.csv`` parsed (columns from ``recorder.layer_accuracy_rows``:
    ``layer, commanded_cum_mm, actual_cum_mm, deviation_mm`` — actual/deviation may be ``None``
    or ``""`` when a layer window had no telemetry, and those points are dropped rather than
    rendered as a false 0. Drift shows as the actual line walking outside the band.
    """
    plt, fig, ax = _new_axes()
    layers = [_opt_float(r.get("layer")) for r in rows]
    cmd_cum = [_opt_float(r.get("commanded_cum_mm")) for r in rows]
    act_cum = [_opt_float(r.get("actual_cum_mm")) for r in rows]

    def _xy(vals: list[float | None]) -> list[tuple[float, float]]:
        pairs = zip(layers, vals, strict=True)
        return [(x, y) for x, y in pairs if x is not None and y is not None]

    cmd_xy = _xy(cmd_cum)
    act_xy = _xy(act_cum)

    if cmd_xy:
        cx, cy = zip(*cmd_xy, strict=True)
        ax.fill_between(
            cx, [y - tol_mm for y in cy], [y + tol_mm for y in cy],
            color=_OK, alpha=0.15, zorder=0, label=f"±{tol_mm:g} mm band",
        )
        ax.plot(cx, cy, color=_MUTED, lw=1.6, marker="o", ms=4, zorder=2, label="commanded")
    if act_xy:
        axx, axy = zip(*act_xy, strict=True)
        ax.plot(axx, axy, color=_ACCENT, lw=1.8, marker="s", ms=4, zorder=3, label="actual")
    if not cmd_xy and not act_xy:
        ax.text(0.5, 0.5, "no layer data", ha="center", va="center",
                transform=ax.transAxes, color=_MUTED)

    ax.set_xlabel("layer")
    ax.set_ylabel("cumulative build height (mm)")
    ax.set_title("Layer accuracy: commanded vs actual height")
    if cmd_xy or act_xy:
        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    return _fig_bytes(plt, fig, fmt)


def render_validation(
    residuals_mm: list[float],
    target_mm: float,
    fmt: str = "png",
) -> bytes:
    """Histogram of world-space scale residuals (mm) against the ±``target_mm`` acceptance line.

    ``residuals_mm`` is ``ScaleResult.residuals_mm`` (vision/validation.py): absolute per-gap
    spacing errors from a certified chessboard. The dashed line is the per-gap tolerance; bars to
    its right are out-of-spec gaps. The worst gap (max) drives PASS/FAIL, shown in the title.
    """
    plt, fig, ax = _new_axes()
    vals = [float(v) for v in residuals_mm]
    if vals:
        import seaborn as sns

        sns.histplot(vals, ax=ax, color=_ACCENT, edgecolor=_INK, alpha=0.8, bins="auto")
        worst = max(vals)
        verdict = "PASS" if worst <= target_mm else "FAIL"
        ax.axvline(target_mm, color=_OK, lw=1.6, ls="--", label=f"target {target_mm:g} mm")
        ax.axvline(worst, color="#b00020", lw=1.4, ls=":", label=f"worst {worst:.3f} mm")
        ax.set_title(f"Scale validation residuals — {verdict} (max {worst:.3f} / {target_mm:g} mm)")
        ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    else:
        ax.text(0.5, 0.5, "no residuals", ha="center", va="center",
                transform=ax.transAxes, color=_MUTED)
        ax.set_title("Scale validation residuals")

    ax.set_xlabel("adjacent-corner spacing error (mm)")
    ax.set_ylabel("count")
    return _fig_bytes(plt, fig, fmt)


def render_sweep(rows: list[dict[str, Any]], fmt: str = "png") -> bytes:
    """Piston hysteresis loop: commanded position vs deviation, split by travel direction.

    ``rows`` is ``piston_sweep.py`` output (keys ``commanded_mm``, ``deviation_mm``,
    ``direction`` in {up, down}). A gap between the up and down clouds at the same commanded
    position is the mechanical backlash the sweep exists to quantify.
    """
    import pandas as pd
    import seaborn as sns

    plt, fig, ax = _new_axes()
    clean = [
        {
            "commanded_mm": _opt_float(r.get("commanded_mm")),
            "deviation_mm": _opt_float(r.get("deviation_mm")),
            "direction": str(r.get("direction") or "?"),
        }
        for r in rows
    ]
    clean = [r for r in clean if r["commanded_mm"] is not None and r["deviation_mm"] is not None]
    ax.axhline(0.0, color=_MUTED, lw=1.0, zorder=1)
    if clean:
        df = pd.DataFrame(clean)
        palette = {"down": _ACCENT, "up": "#3a6ea5", "?": _MUTED}
        sns.scatterplot(
            data=df, x="commanded_mm", y="deviation_mm", hue="direction",
            palette=palette, ax=ax, s=40, alpha=0.8, zorder=3,
        )
        ax.legend(title="direction", loc="best", fontsize=8, framealpha=0.9)
    else:
        ax.text(0.5, 0.5, "no sweep data", ha="center", va="center",
                transform=ax.transAxes, color=_MUTED)

    ax.set_xlabel("commanded position (mm)")
    ax.set_ylabel("deviation actual − commanded (mm)")
    ax.set_title("Piston sweep hysteresis (up vs down)")
    return _fig_bytes(plt, fig, fmt)
