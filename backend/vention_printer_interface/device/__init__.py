"""Transport registry — mirrors the FLIR camera registry and the T&C transport registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vention_printer_interface.device.base import Transport, TransportError

_REGISTRY: dict[str, Callable[..., Transport]] = {}


def register_transport(
    name: str,
) -> Callable[[Callable[..., Transport]], Callable[..., Transport]]:
    def deco(factory: Callable[..., Transport]) -> Callable[..., Transport]:
        _REGISTRY[name] = factory
        return factory

    return deco


def create_transport(name: str, **kwargs: Any) -> Transport:
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown transport {name!r}; known: {sorted(_REGISTRY)}") from exc
    return factory(**kwargs)


def registered_transports() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "Transport",
    "TransportError",
    "create_transport",
    "register_transport",
    "registered_transports",
]

# Self-register built-ins (import for side effect; after the registry exists).
from vention_printer_interface.device import machinemotion as _machinemotion  # noqa: E402,F401
from vention_printer_interface.device import simulated as _simulated  # noqa: E402,F401
