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
gibt, steht in app/gui/module_registry.py.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, Qt, QUrl
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from app import APP_NAME, version_label
from app.core.errors import AppError, Severity
from app.gui.common import window_state
from app.gui.module_registry import ModuleRegistry
from app.gui.status.error_bridge import ErrorBridge
from app.gui.status.problem_panel import ProblemPanel
from app.gui.status.status_bar import StatusBar
from app.gui.tab_manager import TabManager
from app.gui.theme import stylesheet
from app.services.context import AppContext

#: Fenstergroesse beim allerersten Start, Breite x Hoehe in Bildpunkten.
#: ---> HIER STELLT MAN DIE STARTGROESSE DES FENSTERS EIN.
#:
#: Nur beim ALLERERSTEN Start. Danach gilt, was der Benutzer eingestellt hat:
#: beim Schliessen merkt sich das Fenster Groesse und Lage und stellt sie beim
#: naechsten Mal wieder her (siehe _restore_geometry und closeEvent). Wer die
#: Vorgabe hier aendert und sie sehen will, muss den gemerkten Wert loeschen -
#: wo der liegt, steht in app/gui/common/window_state.py.
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

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)

        self._status = StatusBar(self)
        self._status.problems_clicked.connect(self.show_problems)
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
            from app.gui.help.formula_dialog import FormulaHelpDialog

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
        store = window_state.store(SETTINGS_SECTION)
        geometry = store.value("geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        else:
            self.resize(*DEFAULT_SIZE)
        index = store.value("tab_index")
        try:
            self._tabs.setCurrentIndex(int(index))
        except (TypeError, ValueError):
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt-Namensschema
        store = window_state.store(SETTINGS_SECTION)
        store.setValue("geometry", self.saveGeometry())
        store.setValue("tab_index", self._tabs.currentIndex())

        self._tab_manager.shutdown()
        self._bridge.detach()
        self._context.jobs.cancel_all()
        self._context.jobs.wait_for_done(2000)
        super().closeEvent(event)
