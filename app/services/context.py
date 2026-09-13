"""Das Buendel, das ein Berechnungsmodul zum Arbeiten braucht.

Ein Tab bekommt genau dieses Objekt und sonst nichts. Er baut sich seine
Services nicht selbst zusammen und kennt keine Konstruktoren - das passiert
ausschliesslich in der Composition Root (app/application.py).

Der Nutzen zeigt sich beim vierten Berechnungsmodul: es bekommt denselben
Kontext und muss dafuer weder an der Composition Root noch am Hauptfenster
etwas aendern.

Zur Schichtregel: diese Datei und die uebrige Serviceschicht duerfen QtCore
benutzen - Signale sind der einzige threadsichere Weg, ein Ergebnis aus einem
Worker in die Oberflaeche zu bringen. Verboten bleiben QtWidgets, QtGui und
jeder Import aus app.gui. Die Serviceschicht kennt damit Nebenlaeufigkeit, aber
keine Bedienelemente. tests/test_architecture.py prueft das.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings_service import SettingsService
from app.core.errors import ErrorReporter
from app.core.requests import RequestGate
from app.jobs.job_manager import JobManager
from app.services.app_state import AppState
from app.services.package_service import PackageService
from app.services.pallet_service import PalletService
from app.services.vacuum_service import VacuumService


@dataclass(frozen=True, slots=True)
class AppContext:
    """Alles, was ein Berechnungsmodul von der Anwendung sehen darf."""

    state: AppState
    settings: SettingsService
    reporter: ErrorReporter
    jobs: JobManager
    gate: RequestGate
    packages: PackageService
    pallets: PalletService
    vacuum: VacuumService

    #: Wartezeit, bevor eine Eingabeaenderung eine Berechnung ausloest.
    #: Ohne Entprellung startet jeder Tastendruck einen eigenen Rechenlauf
    #: (Spezifikation 32).
    debounce_ms: int = 200
