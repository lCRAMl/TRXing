"""Serviceschicht fuer die Paketdaten.

Der Tab liest Zahlen aus Eingabefeldern und baut daraus ein PackageSpec. Ob das
Paket gueltig ist, entscheidet er nicht - das tut die Validierung im DTO-Modul,
aufgerufen von hier. So steht die Regel "Laenge groesser null" an genau einer
Stelle und nicht in jedem Widget noch einmal.

Ungueltige Eingaben kommen nicht in den Zustand. Waeren sie drin, muesste jede
Berechnung fuer sich pruefen, ob das Paket brauchbar ist; stattdessen gilt:
was im Zustand steht, ist gueltig.
"""

from __future__ import annotations

from app.core.errors import ErrorReporter
from app.core.result import ValidationReport
from app.dto.package import PackageSpec, validate_package
from app.services.app_state import AppState


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
