"""Vention Printer Interface.

Simulator-first, safety-first operator for the MachineMotion 2 binder-jet printer. A connected
controller is read-only until ARMed; the heater output turns on only by explicit operator action
and is forced off on any fault, disconnect, E-STOP, or watchdog expiry. Only
``device/machinemotion.py`` opens sockets to the controller.
"""

__version__ = "0.8.4"
