"""Der gemeinsame Zustand - und wie er beschrieben wird.

Absichtlich klein: das aktuelle Paket und die Auswahl der Tabs. Nichts darin
ist ein Widget, nichts darin ist ein Rechenergebnis.

Der Revisionszaehler ist das Herzstueck. Jede fachliche Aenderung erhoeht ihn.
Ein Ergebnis merkt sich in seinen Metadaten die Revision, unter der es
entstand; weichen beide ab, ist die Anzeige veraltet. Das genuegt, damit jeder
Tab eine Paketaenderung bemerkt, ohne dass Signale von Tab zu Tab gereicht
werden.

Dazu die Pruefung und Uebernahme der Paketdaten - sie war bisher ein eigener
Dienst, ist aber nichts anderes als der geregelte Weg, dieses eine Feld zu
beschreiben.

Qt-frei, damit auch Rechenteile zuhoeren koennen, ohne eine QApplication zu
brauchen. Die Bruecke zu Qt-Signalen liegt in der Oberflaechenschicht.

Zusammengelegt aus services/app_state.py und services/package_service.py.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable
from app.fach.paket import PackageSpec
from app.technik.fehler import ErrorReporter
from app.fach.ergebnis import ValidationReport
from app.fach.paket import PackageSpec, validate_package


# ---------------------------------------------------------------------------
# vorgang.py
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# package_service.py
# ---------------------------------------------------------------------------
"""Serviceschicht fuer die Paketdaten.

Der Tab liest Zahlen aus Eingabefeldern und baut daraus ein PackageSpec. Ob das
Paket gueltig ist, entscheidet er nicht - das tut die Validierung im DTO-Modul,
aufgerufen von hier. So steht die Regel "Laenge groesser null" an genau einer
Stelle und nicht in jedem Widget noch einmal.

Ungueltige Eingaben kommen nicht in den Zustand. Waeren sie drin, muesste jede
Berechnung fuer sich pruefen, ob das Paket brauchbar ist; stattdessen gilt:
was im Zustand steht, ist gueltig.
"""

class PackageService:
    """Oeffentliche Schnittstelle der Paketdaten."""

    def __init__(self, state: AppState, reporter: ErrorReporter) -> None:
        self._state = state
        self._reporter = reporter

    def get_current_package(self) -> PackageSpec | None:
        return self._state.snapshot().package

    def validate(self, package: PackageSpec) -> ValidationReport:
        """Prueft ein Paket, ohne den Zustand zu beruehren.

        Der Tab ruft das bei jeder Eingabe auf, um Fehler direkt am Feld
        anzuzeigen - auch dann, wenn der Wert nicht uebernommen werden kann.
        """
        return validate_package(package)

    def update_package(self, package: PackageSpec) -> ValidationReport:
        """Uebernimmt ein Paket in den Zustand, sofern es gueltig ist.

        Gibt den Pruefbericht zurueck. Bei Fehlern bleibt der bisherige Zustand
        unveraendert und die abhaengigen Tabs behalten ihr Ergebnis - es gehoert
        ja noch zum letzten gueltigen Paket.
        """
        report = validate_package(package)
        if not report.ok:
            return report

        changed = self._state.set_package(package)
        if changed:
            self._reporter.info(
                "package",
                "Paket uebernommen: "
                + format(package.length_mm, ".0f") + "x"
                + format(package.width_mm, ".0f") + "x"
                + format(package.height_mm, ".0f") + " mm, "
                + format(package.weight_kg, ".3f") + " kg",
            )
        return report

    def clear(self) -> None:
        """Entfernt das Paket. Abhaengige Anzeigen werden dadurch veraltet."""
        self._state.set_package(None)
