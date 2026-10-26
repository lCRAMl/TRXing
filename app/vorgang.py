"""Der gemeinsame Anwendungszustand (Spezifikation 30).

Absichtlich klein: das aktuelle Paket und die Auswahl der drei Tabs. Nichts
darin ist ein Widget, nichts darin ist ein Ergebnis. Rechenergebnisse gehoeren
den Tabs, die sie angefordert haben.

Der Revisionszaehler ist das Herzstueck. Jede fachliche Aenderung erhoeht ihn.
Ein Ergebnis merkt sich in seinen Metadaten die Revision, unter der es
entstanden ist. Weichen beide ab, ist die Anzeige veraltet - das genuegt, damit
jeder Tab eine Paketaenderung bemerkt, ohne dass das Paketformular ihn kennen
oder Signale von Tab zu Tab gereicht werden muessen.

Benachrichtigt wird ueber gewoehnliche Rueckrufe statt ueber Qt-Signale, damit
auch Jobs und Engines zuhoeren koennen, ohne eine QApplication zu brauchen. Die
Bruecke zu Qt-Signalen liegt in der Oberflaechenschicht.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable

from app.dto.package import PackageSpec


class StateChange(Enum):
    """Was sich geaendert hat. Empfaenger koennen danach filtern."""

    PACKAGE = "package"
    PALLET = "pallet"
    PATTERN = "pattern"
    SUCTION_CUP = "suction_cup"
    PLATE = "plate"

    @property
    def label(self) -> str:
        return {
            StateChange.PACKAGE: "Paketdaten",
            StateChange.PALLET: "Palettentyp",
            StateChange.PATTERN: "Palettiermuster",
            StateChange.SUCTION_CUP: "Saugertyp",
            StateChange.PLATE: "Vakuumplatte",
        }[self]


#: Welche Aenderung welchen Kanal entwertet. Die eine Stelle, an der die
#: Abhaengigkeiten zwischen den Tabs stehen - sonst waeren sie ueber die
#: Oberflaeche verteilt und beim Hinzufuegen eines Moduls nicht auffindbar.
INVALIDATES: dict[StateChange, tuple[str, ...]] = {
    StateChange.PACKAGE: ("pallet", "vacuum"),
    StateChange.PALLET: ("pallet",),
    StateChange.PATTERN: ("pallet", "vacuum"),
    StateChange.SUCTION_CUP: ("vacuum",),
    StateChange.PLATE: ("vacuum",),
}


@dataclass(frozen=True, slots=True)
class AppStateSnapshot:
    """Unveraenderliche Momentaufnahme. Wird an Empfaenger uebergeben, damit
    niemand den lebenden Zustand unter der Hand aendert."""

    revision: int = 0
    package: PackageSpec | None = None
    pallet_id: str | None = None
    pattern_id: str | None = None
    suction_cup_id: str | None = None

    @property
    def has_package(self) -> bool:
        return self.package is not None


Listener = Callable[[StateChange, AppStateSnapshot], None]


class AppState:
    """Haelt den Zustand und benachrichtigt ueber Aenderungen.

    Threadsicher, weil Engines den Zustand aus einem Worker lesen duerfen -
    schreiben darf ihn nur die Serviceschicht.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot = AppStateSnapshot()
        self._listeners: list[Listener] = []

    # Lesen --------------------------------------------------------------------

    def snapshot(self) -> AppStateSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def revision(self) -> int:
        with self._lock:
            return self._snapshot.revision

    def is_stale(self, result_revision: int) -> bool:
        """Ob ein unter dieser Revision entstandenes Ergebnis veraltet ist."""
        return result_revision != self.revision

    # Schreiben ----------------------------------------------------------------

    def set_package(self, package: PackageSpec | None) -> bool:
        return self._update(StateChange.PACKAGE, package=package)

    def set_pallet_id(self, pallet_id: str | None) -> bool:
        return self._update(StateChange.PALLET, pallet_id=pallet_id)

    def set_pattern_id(self, pattern_id: str | None) -> bool:
        return self._update(StateChange.PATTERN, pattern_id=pattern_id)

    def set_suction_cup_id(self, cup_id: str | None) -> bool:
        return self._update(StateChange.SUCTION_CUP, suction_cup_id=cup_id)

    def notify_plate_changed(self) -> None:
        """Die Plattengeometrie gehoert dem Vakuumtab, entwertet aber dessen
        Ergebnis genauso. Sie wird deshalb nur gemeldet, nicht gespeichert."""
        self._bump(StateChange.PLATE)

    def _update(self, change: StateChange, **fields) -> bool:
        """Setzt Felder und meldet die Aenderung. Gibt zurueck, ob sich etwas
        geaendert hat - eine Neueingabe desselben Werts loest nichts aus und
        entwertet damit auch kein gueltiges Ergebnis."""
        with self._lock:
            current = self._snapshot
            unchanged = all(getattr(current, key) == value for key, value in fields.items())
            if unchanged:
                return False
            self._snapshot = replace(current, revision=current.revision + 1, **fields)
            snapshot = self._snapshot
            listeners = tuple(self._listeners)

        for listener in listeners:
            listener(change, snapshot)
        return True

    def _bump(self, change: StateChange) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, revision=self._snapshot.revision + 1)
            snapshot = self._snapshot
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(change, snapshot)

    # Benachrichtigung ---------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    @staticmethod
    def invalidated_channels(change: StateChange) -> tuple[str, ...]:
        return INVALIDATES.get(change, ())
