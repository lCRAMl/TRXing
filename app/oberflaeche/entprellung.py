"""Die Entprellung: schnelle Aenderungen zu einem Aufruf sammeln.

Lag kurzzeitig in qt_controls_pyrs. Kein Widget und kein Aussehen -
deshalb am 2026-10-31 zurueck hierher.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget


class Debouncer:
    """Sammelt schnelle Aenderungen zu einem Aufruf.

    Ohne diese Bremse startet jeder Tastendruck in einem Zahlenfeld einen
    eigenen Durchlauf: aus "100", "1000", "10000" werden drei Berechnungen,
    von denen zwei sofort wieder verworfen werden.

    Kein QWidget, sondern ein Helfer um einen ``QTimer`` - dadurch ist er an
    kein Fenster gebunden und ueberall gleich einsetzbar. ``parent`` dient nur
    der Lebensdauer des Timers.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        delay_ms: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        self._callback = callback
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._fire)

    def trigger(self) -> None:
        """Startet die Wartezeit neu."""
        self._timer.start()

    def cancel(self) -> None:
        """Verwirft, was aussteht."""
        self._timer.stop()

    def flush(self) -> None:
        """Loest sofort aus, falls etwas aussteht.

        Fuer den Moment, in dem die letzte Eingabe sicher drin sein muss -
        bevor ein Reiter verlassen oder ein Fenster geschlossen wird.
        """
        if self._timer.isActive():
            self._timer.stop()
            self._fire()

    def _fire(self) -> None:
        self._callback()

    @property
    def pending(self) -> bool:
        """Ob eine Aenderung auf ihren Aufruf wartet."""
        return self._timer.isActive()
