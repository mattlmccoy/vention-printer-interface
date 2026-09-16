"""Meteor printhead-firing adapter.

The operator drives the MachineMotion axes and the print choreography; the printhead FIRING (jetting
binder in each layer's pattern) is done by **Meteor MetPrint** (Xaar 2001 heads) on a Windows PC.
Meteor receives jobs through a **hot folder**: the RIP writes per-layer TIFFs into it and MetPrint
picks up the job and fires it, advancing pages on each print trigger (encoder / product-detect).

The adapter's job before a build is one honest pre-flight question: does Meteor have a COMPLETE job
loaded for this build? A missing or incomplete job must read as NOT ready — never a false green —
because otherwise the operator spreads powder and sweeps the printhead over a bed with no binder.

Design (see docs/superpowers/specs/2026-09-16-meteor-adapter-design.md):
- ``MeteorAdapter`` protocol + a real ``HotFolderMeteorAdapter`` (filesystem-only, so cross-platform
  and testable) + a ``SimulatedMeteorAdapter`` for tests / dry runs.
- The precise per-sweep trigger (MM digital-output -> Meteor external PD) and the PCMD_* control DLL
  are deferred: the first is blocked on two open hardware facts, the second on Windows + the Meteor
  SDK. ``fire_layer`` / ``end_job`` are no-ops for the hot-folder path (MetPrint auto-advances) and
  exist so a future control adapter can drive firing without changing the choreography.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..jobs.store import JobInfo


@dataclass(frozen=True)
class MeteorStatus:
    """Firing-backend readiness for one build. ``ready`` is true ONLY when a complete job is
    armable; absence, incompleteness, and an unwatched location are each a distinct non-ready
    ``detail``."""

    backend: str
    available: bool
    ready: bool
    job_name: str | None
    layers_ready: int
    layers_expected: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "available": self.available,
            "ready": self.ready,
            "job_name": self.job_name,
            "layers_ready": self.layers_ready,
            "layers_expected": self.layers_expected,
            "detail": self.detail,
        }


@runtime_checkable
class MeteorAdapter(Protocol):
    """A printhead-firing backend. Implementations answer readiness and (for a future control path)
    drive per-layer firing; the hot-folder path leaves firing to MetPrint's own auto-advance."""

    name: str

    def status(self, job: JobInfo | None) -> MeteorStatus:
        """Pre-flight readiness for ``job`` (the operator's selected job, or None)."""
        ...

    def fire_layer(self, layer: int) -> None:
        """Notify that the printhead is about to sweep printing layer ``layer`` (1-based)."""
        ...

    def end_job(self) -> None:
        """Notify that the build is finished."""
        ...


class HotFolderMeteorAdapter:
    """Real Meteor integration for the hot-folder architecture. ``available`` when a watched
    hot-folder root exists; ``ready`` when the selected job is complete (all pages present) AND
    under a watched root, so MetPrint can actually pick it up. ``fire_layer`` / ``end_job`` are
    no-ops: MetPrint advances pages from the hot folder on its own print trigger."""

    name = "hot_folder"

    def __init__(self, roots: list[Path]) -> None:
        self.roots = [Path(r) for r in roots]

    def _available(self) -> bool:
        return any(r.exists() for r in self.roots)

    def _under_watched_root(self, job: JobInfo) -> bool:
        target = job.dir.resolve()
        for root in self.roots:
            if not root.exists():
                continue
            rr = root.resolve()
            if target == rr or rr in target.parents:
                return True
        return False

    def status(self, job: JobInfo | None) -> MeteorStatus:
        available = self._available()
        if not available:
            return MeteorStatus(
                self.name, False, False, None, 0, 0,
                "hot folder not found — is the MetPrint hot-folder path configured?",
            )
        if job is None:
            return MeteorStatus(
                self.name, True, False, None, 0, 0,
                "no job selected — select the sliced job Meteor will fire",
            )
        ready = len(job.pages)  # pages actually present on disk
        expected = job.layer_count
        if not self._under_watched_root(job):
            return MeteorStatus(
                self.name, True, False, job.name, ready, expected,
                "job is not under a watched hot-folder root, so MetPrint cannot pick it up",
            )
        if not job.complete:
            return MeteorStatus(
                self.name, True, False, job.name, ready, expected,
                f"job incomplete — {expected - ready} of {expected} layers missing "
                f"(missing pages {job.missing_pages})",
            )
        return MeteorStatus(
            self.name, True, True, job.name, ready, expected,
            f"ready — {expected} layers loaded in the hot folder",
        )

    def fire_layer(self, layer: int) -> None:  # noqa: D401 - MetPrint auto-advances; nothing to do
        return None

    def end_job(self) -> None:
        return None


class SimulatedMeteorAdapter:
    """In-process fake for tests / dry runs. Always ``available``; ``ready`` iff the job's complete.
    Records fired layers and end-of-job so the choreography hook can be tested without hardware."""

    name = "simulated"

    def __init__(self) -> None:
        self.fired: list[int] = []
        self.ended: bool = False

    def status(self, job: JobInfo | None) -> MeteorStatus:
        if job is None:
            return MeteorStatus(self.name, True, False, None, 0, 0, "no job selected (simulated)")
        ready = len(job.pages)
        expected = job.layer_count
        ok = job.complete
        detail = "ready (simulated)" if ok else f"incomplete (simulated) — {ready}/{expected}"
        return MeteorStatus(self.name, True, ok, job.name, ready, expected, detail)

    def fire_layer(self, layer: int) -> None:
        self.fired.append(layer)

    def end_job(self) -> None:
        self.ended = True
