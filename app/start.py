"""Der Zusammenbau: aus Teilen wird ein Programm.

Hier und nur hier wird gewusst, welche Teile es gibt und wie sie
zusammenhaengen. Alles andere bekommt den fertigen Kontext gereicht und baut
sich seine Dienste nicht selbst.

Drei Dinge in dieser Reihenfolge:

    Application     Dienste bauen, Konfiguration laden, Protokoll einrichten
    ModuleRegistry  welche Rechenmodule es gibt und in welcher Reihenfolge
    MainWindow      das Fenster, die Reiter, Menue und Statuszeile

Die Registry ist der Grund, warum ein viertes Rechenmodul weder das Fenster
noch den Zusammenbau anfasst: es meldet sich an, und der Rest ergibt sich.

Zusammengelegt aus application.py, gui/module_registry.py und
gui/main_window.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from app import APP_NAME, __version__
from app.fach.katalog import ConfigStatus, SettingsService
from app.technik.fehler import ErrorReporter
from app.technik.fehler import LoggingSink, install_excepthooks, setup_logging
from app.technik.pfade import config_dir, log_dir
from app.technik.nebenlaeufig import RequestGate
from app.technik.nebenlaeufig import JobManager, PoolConfig
from app.fach.vorgang import AppState
from app.fach.vorgang import PackageService
from app.palette.dienst import PalletService
from app.vakuum.dienst import VacuumService
from typing import Protocol, runtime_checkable
from PyQt6.QtWidgets import QWidget
from app.kontext import AppContext
from PyQt6.QtCore import QByteArray, Qt, QUrl
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QTabWidget
from app import APP_NAME, version_label
from app.technik.fehler import AppError, Severity
from app.oberflaeche.bedienelemente import restore_splitter, save_splitter, store
from app.oberflaeche.meldungen import ErrorBridge
from app.oberflaeche.meldungen import ProblemPanel
from app.oberflaeche.meldungen import StatusBar
from app.tabs import CalculationModule, ModuleRegistry, TabManager
from qt_controls_pyrs import HaloTabWidget
from app.oberflaeche.darstellung import stylesheet


# ---------------------------------------------------------------------------
# application.py
# ---------------------------------------------------------------------------
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
        from app.kontext import AppContext

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

        from app.tabs import default_modules

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


# ---------------------------------------------------------------------------
# main_window.py
# ---------------------------------------------------------------------------
"""Hauptfenster.

    +--------------------------------------------------------------+
    |  Berechnungen                                                |
    +--------------------------------------------------------------+
    | [ Palettierung ] [ Vakuumplatte ]                            |
    +--------------------------------------------------------------+
    |                        Tab-Inhalt                            |
    +--------------------------------------------------------------+
    | Status / Berechnung / Warnungen                              |
    +--------------------------------------------------------------+

Das Fenster enthaelt keine Fachlogik und keine Modulkenntnis. Es haengt die
Statusleiste an die Signale von JobManager und ErrorReporter, laesst den
TabManager die Tabs bauen und merkt sich die Fenstergeometrie. Welche Module es
gibt, steht in app/start.py.
"""

DEFAULT_SIZE = (1600, 1000)

#: Abschnitt, unter dem sich das Fenster seine Geometrie merkt.
SETTINGS_SECTION = "MainWindow"


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, registry: ModuleRegistry) -> None:
        super().__init__()
        self._context = context
        self._registry = registry
        self._problem_panel: ProblemPanel | None = None
        self._formula_help = None

        self.setWindowTitle(version_label())
        self.setStyleSheet(stylesheet())

        # Halo-Reiter: beim Wechsel gleitet ein Strich zum neuen Reiter,
        # und der Inhalt schiebt sich seitlich hinaus.
        self._tabs = HaloTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)

        self._status = StatusBar(self)
        self._status.problems_clicked.connect(self.show_problems)
        # Die Leiste sieht, DASS gerechnet wird, aber nicht, von wem. Abgebrochen
        # wird deshalb alles Laufende - zwei Kanaele hat die Anwendung, und wer
        # auf den Abbruch neben dem Fortschrittsbalken drueckt, meint den
        # Fortschritt, den er sieht.
        self._status.cancel_requested.connect(context.jobs.cancel_all)
        self.setStatusBar(self._status)

        self._bridge = ErrorBridge(context.reporter, self)
        self._bridge.error_reported.connect(self._on_error, Qt.ConnectionType.QueuedConnection)

        context.jobs.activity_changed.connect(self._status.set_activity)
        context.jobs.job_progress.connect(self._on_progress)

        self._tab_manager = TabManager(self._tabs, registry, context, context.reporter, self)
        self._tab_manager.build()

        self._build_menu()
        self._show_config_status()
        self._restore_geometry()
        self._status.show_status("Bereit")

    # Menue --------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")

        reload_action = QAction("Konfiguration neu laden", self)
        reload_action.setShortcut(QKeySequence("F5"))
        reload_action.setStatusTip("Liest pallets.json, pallet_patterns.json, suction_cups.json und vacuum_defaults.json neu ein")
        reload_action.triggered.connect(self._reload_config)
        file_menu.addAction(reload_action)

        open_action = QAction("Konfigurationsordner oeffnen", self)
        open_action.triggered.connect(self._open_config_dir)
        file_menu.addAction(open_action)

        file_menu.addSeparator()
        quit_action = QAction("Beenden", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&Ansicht")
        problems_action = QAction("Probleme anzeigen", self)
        problems_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        problems_action.triggered.connect(self.show_problems)
        view_menu.addAction(problems_action)

        help_menu = self.menuBar().addMenu("&Hilfe")

        formulas_action = QAction("Rechenwege und Formeln", self)
        formulas_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        formulas_action.setStatusTip(
            "Erklaert jede Berechnung der Anwendung - mathematisch und mit Verweis auf den Quelltext"
        )
        formulas_action.triggered.connect(self.show_formulas)
        help_menu.addAction(formulas_action)

        help_menu.addSeparator()
        about_action = QAction("Ueber " + APP_NAME, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # Ereignisse ---------------------------------------------------------------

    def _on_error(self, error: AppError) -> None:
        self._status.show_error(error)
        self._status.set_problem_count(self._context.reporter.problems.count(Severity.WARNING))
        if self._problem_panel is not None and self._problem_panel.isVisible():
            self._problem_panel.refresh()

    def _on_progress(self, job_id: int, current: int, total: int, text: str) -> None:
        self._status.set_progress(current, total, text)

    def _on_tab_changed(self, index: int) -> None:
        """Tabwechsel: erst uebernehmen, dann nachrechnen.

        Die Reihenfolge ist entscheidend. Zuerst muessen die verlassenen Tabs
        ihre noch entprellten Eingaben in den Zustand schreiben - sonst wechselt
        man von den Paketdaten zur Vakuumplatte, bevor die Entprellung
        abgelaufen ist, und der neue Tab rechnet mit dem vorigen Paket.

        Erst danach wird der aufgeschlagene Tab benachrichtigt. Er rechnet dann
        mit den gerade uebernommenen Werten neu, falls sich seit seinem letzten
        Ergebnis etwas geaendert hat.
        """
        current = self._tabs.currentWidget()

        for module_id in self._registry.ids():
            widget = self._tab_manager.widget_for(module_id)
            if widget is None or widget is current:
                continue
            commit = getattr(widget, "commit_now", None)
            if commit is None:
                continue
            try:
                commit()
            except Exception as exc:
                self._context.reporter.exception(exc, source="gui", module=module_id)

        activated = getattr(current, "on_activated", None)
        if activated is not None:
            try:
                activated()
            except Exception as exc:
                self._context.reporter.exception(exc, source="gui", tab=index)

    # Aktionen -----------------------------------------------------------------

    def _reload_config(self) -> None:
        status = self._context.settings.load()
        self._show_config_status()
        if status.ok:
            self._status.show_status("Konfiguration neu geladen: " + str(status.pallet_count) + " Paletten, "
                                     + str(status.pattern_count) + " Muster, " + str(status.cup_count) + " Sauger")
        else:
            self._status.show_status("Konfiguration mit Beanstandungen geladen - siehe Probleme")

    def _open_config_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._context.settings.directory)))

    def _show_config_status(self) -> None:
        status = self._context.settings.status()
        if status is None:
            return
        text = (str(status.pallet_count) + " Paletten | " + str(status.pattern_count) + " Muster | "
                + str(status.cup_count) + " Sauger")
        self._status.set_config_info(text, "Konfiguration aus " + str(status.directory))

    def show_problems(self) -> None:
        if self._problem_panel is None:
            self._problem_panel = ProblemPanel(self._context.reporter, self)
        self._problem_panel.refresh()
        self._problem_panel.show()
        self._problem_panel.raise_()
        self._problem_panel.activateWindow()

    def show_formulas(self) -> None:
        """Oeffnet die Rechenwegdokumentation.

        Nicht modal und nur einmal erzeugt: man liest die Erklaerung, waehrend
        die zugehoerigen Werte im Tab danebenstehen, und findet beim
        Wiederoeffnen die Stelle wieder, an der man war.
        """
        if self._formula_help is None:
            from app.oberflaeche.hilfe import FormulaHelpDialog

            self._formula_help = FormulaHelpDialog(self)
        self._formula_help.show()
        self._formula_help.raise_()
        self._formula_help.activateWindow()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "Ueber " + APP_NAME,
            version_label() + "\n\n"
            "Modulare Sammlung technischer Berechnungsprogramme.\n\n"
            "Module: " + ", ".join(m.title for m in self._registry.modules()) + "\n"
            "Konfiguration: " + str(self._context.settings.directory),
        )

    # Fenstergeometrie ---------------------------------------------------------

    def _restore_geometry(self) -> None:
        einstellungen = store(SETTINGS_SECTION)
        geometry = einstellungen.value("geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        else:
            self.resize(*DEFAULT_SIZE)
        index = einstellungen.value("tab_index")
        try:
            self._tabs.setCurrentIndex(int(index))
        except (TypeError, ValueError):
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt-Namensschema
        einstellungen = store(SETTINGS_SECTION)
        einstellungen.setValue("geometry", self.saveGeometry())
        einstellungen.setValue("tab_index", self._tabs.currentIndex())

        self._tab_manager.shutdown()
        self._bridge.detach()
        self._context.jobs.cancel_all()
        self._context.jobs.wait_for_done(2000)
        super().closeEvent(event)
