"""Composition Root - hier und nur hier werden die Schichten verdrahtet.

Startsequenz (Reihenfolge ist bindend):

    1. Logging einrichten, Ausnahmehaken installieren
    2. ErrorReporter mit Protokollsenke aufsetzen
    3. Konfiguration laden und pruefen
    4. Anwendungszustand anlegen
    5. JobManager starten
    6. Services erzeugen
    7. AppContext buendeln
    8. Modulregistry fuellen

Erst danach darf ein Fenster entstehen. Schritt 3 kann mit Beanstandungen enden,
ohne den Start zu verhindern - die Konfigurationsschicht weicht auf eingebaute
Mindestdaten aus und meldet, was fehlt.

Kein Tab baut sich seine Services selbst zusammen. Genau das ist der Zweck
dieser Datei: ein neues Berechnungsmodul bekommt denselben Kontext und aendert
hier nichts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import APP_NAME, __version__
from app.config.settings_service import ConfigStatus, SettingsService
from app.core.errors import ErrorReporter
from app.core.logging_setup import LoggingSink, install_excepthooks, setup_logging
from app.core.paths import config_dir, log_dir
from app.core.requests import RequestGate
from app.jobs.job_manager import JobManager, PoolConfig
from app.services.app_state import AppState
from app.services.package_service import PackageService
from app.services.pallet_service import PalletService
from app.services.vacuum_service import VacuumService


@dataclass
class StartupResult:
    ok: bool = True
    message: str = ""
    notes: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    config_status: ConfigStatus | None = None


class Application:
    """Haelt die langlebigen Komponenten und ihren Lebenszyklus."""

    def __init__(self, config_directory: Path | None = None, log_directory: Path | None = None) -> None:
        self._config_directory = config_directory
        self._log_directory = log_directory

        self.reporter = ErrorReporter()
        self.settings: SettingsService | None = None
        self.state: AppState | None = None
        self.jobs: JobManager | None = None
        self.gate: RequestGate | None = None
        self.packages: PackageService | None = None
        self.pallets: PalletService | None = None
        self.vacuum: VacuumService | None = None
        self.context = None
        self.registry = None
        self.log_file: Path | None = None
        self._started = False

    # Start --------------------------------------------------------------------

    def startup(self) -> StartupResult:
        started = time.perf_counter()
        notes: list[str] = []

        self.log_file = setup_logging(directory=self._log_directory or log_dir())
        self.reporter.add_sink(LoggingSink())
        install_excepthooks(self.reporter)
        logging.getLogger("app").info("%s %s startet", APP_NAME, __version__)

        directory = self._config_directory or config_dir()
        self.settings = SettingsService(directory, self.reporter)
        config_status = self.settings.load()
        if not config_status.ok:
            if config_status.failed_files:
                notes.append("Nicht gelesen: " + ", ".join(config_status.failed_files))
            if config_status.used_builtin:
                notes.append("Notfalldaten aktiv fuer: " + ", ".join(config_status.used_builtin))

        self.state = AppState()
        self.gate = RequestGate()
        self.jobs = JobManager(self.reporter, PoolConfig())
        self.packages = PackageService(self.state, self.reporter)
        self.pallets = PalletService(self.jobs, self.gate, self.reporter, self.settings)
        self.vacuum = VacuumService(self.jobs, self.gate, self.reporter, self.settings)

        # Erst hier, damit der Kontext keine halb aufgebauten Komponenten sieht.
        from app.services.context import AppContext

        self.context = AppContext(
            state=self.state,
            settings=self.settings,
            reporter=self.reporter,
            jobs=self.jobs,
            gate=self.gate,
            packages=self.packages,
            pallets=self.pallets,
            vacuum=self.vacuum,
        )

        from app.gui.module_registry import ModuleRegistry, default_modules

        self.registry = ModuleRegistry()
        self.registry.register_all(default_modules())

        self._started = True
        duration = time.perf_counter() - started
        logging.getLogger("app").info(
            "Start abgeschlossen in %.3f s, %d Module", duration, len(self.registry)
        )
        return StartupResult(ok=True, notes=notes, duration_s=duration, config_status=config_status)

    # Bericht ------------------------------------------------------------------

    def status_report(self) -> dict:
        """Kurzbericht fuer --check. Keine Objektabbilder (Spezifikation 40)."""
        config_status = self.settings.status() if self.settings else None
        return {
            "version": __version__,
            "log_file": str(self.log_file) if self.log_file else "",
            "config_dir": str(self.settings.directory) if self.settings else "",
            "pallets": config_status.pallet_count if config_status else 0,
            "patterns": config_status.pattern_count if config_status else 0,
            "suction_cups": config_status.cup_count if config_status else 0,
            "config_ok": bool(config_status and config_status.ok),
            "modules": list(self.registry.ids()) if self.registry else [],
            "pools": self.jobs.pool_sizes() if self.jobs else {},
            "problems": self.reporter.problems.count(),
        }

    # Ende ---------------------------------------------------------------------

    def shutdown(self) -> None:
        if self.jobs is not None:
            self.jobs.cancel_all()
            self.jobs.wait_for_done(3000)
        if self._started:
            logging.getLogger("app").info("%s beendet", APP_NAME)
        logging.shutdown()
        self._started = False
