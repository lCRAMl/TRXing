"""Baut die Tabs aus der Modulliste.

Das Hauptfenster kennt weder die Anzahl noch die Namen der Berechnungsmodule.
Es uebergibt Registry und Kontext, bekommt gefuellte Tabs zurueck und ist
fertig. Kein `if tab == 2` (Spezifikation 06).

Scheitert ein Modul beim Aufbau, bekommt es einen Platzhalter-Tab mit der
Fehlermeldung statt gar keinen. Sonst verschwindet das Modul kommentarlos aus
der Leiste, und niemand sucht den Grund an der richtigen Stelle.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from app.core.errors import AppError, ErrorReporter, Severity
from app.gui.module_registry import CalculationModule, ModuleRegistry
from app.gui.theme import PALETTE
from app.services.app_state import AppStateSnapshot, StateChange
from app.services.context import AppContext


class TabHost(QWidget):
    """Vertrag, den ein Tab optional erfuellen darf.

    Ein Tab MUSS nichts davon anbieten - dann bekommt er einfach keine
    Benachrichtigungen.
    """

    def on_state_changed(self, change: StateChange, snapshot: AppStateSnapshot) -> None:
        """Eine fachliche Aenderung ist eingetreten. Im Oberflaechen-Thread."""

    def on_activated(self) -> None:
        """Der Tab ist in den Vordergrund gekommen.

        Hier gehoert das Nachrechnen hin. Waehrend der Benutzer im sichtbaren
        Tab tippt, rechnen die verdeckten bewusst nicht mit - das waere
        Rechenzeit fuer Ergebnisse, die niemand ansieht. Sie merken sich nur,
        dass sie veraltet sind, und holen es nach, sobald man sie aufschlaegt.
        """

    def commit_now(self) -> None:
        """Ausstehende Eingaben sofort uebernehmen, bevor der Tab verlassen wird."""

    def shutdown(self) -> None:
        """Wird vor dem Schliessen des Fensters aufgerufen."""


def _failure_widget(module_id: str, message: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(
        "Das Modul '" + module_id + "' konnte nicht geladen werden.\n\n" + message
        + "\n\nEinzelheiten stehen in der Problemliste."
    )
    label.setWordWrap(True)
    label.setStyleSheet("color: " + PALETTE.error + "; padding: 24px;")
    layout.addWidget(label)
    layout.addStretch(1)
    return widget


class TabManager(QObject):
    """Erzeugt die Tabs und reicht Zustandsaenderungen an sie weiter."""

    tab_failed = pyqtSignal(str, str)

    def __init__(
        self,
        tabs: QTabWidget,
        registry: ModuleRegistry,
        context: AppContext,
        reporter: ErrorReporter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._registry = registry
        self._context = context
        self._reporter = reporter
        self._widgets: dict[str, QWidget] = {}

    def build(self) -> None:
        """Legt fuer jedes registrierte Modul einen Tab an."""
        for module in self._registry.modules():
            self._add(module)
        # Die Weitergabe wird erst angemeldet, wenn alle Tabs stehen - sonst
        # bekaeme ein halb aufgebauter Tab bereits Benachrichtigungen.
        self._context.state.add_listener(self._on_state_changed)

    def _add(self, module: CalculationModule) -> None:
        try:
            widget = module.create_widget(self._context)
        except Exception as exc:
            self._reporter.report(
                AppError.from_exception(
                    exc, source="gui",
                    severity=Severity.ERROR,
                    message="Modul '" + module.module_id + "' konnte nicht aufgebaut werden: " + str(exc),
                )
            )
            widget = _failure_widget(module.module_id, str(exc))
            self.tab_failed.emit(module.module_id, str(exc))
        self._widgets[module.module_id] = widget
        self._tabs.addTab(widget, module.title)

    def _on_state_changed(self, change: StateChange, snapshot: AppStateSnapshot) -> None:
        """Ein Fehler in einem Tab darf die uebrigen nicht um ihre
        Benachrichtigung bringen - deshalb jeder Aufruf einzeln gekapselt."""
        for module_id, widget in self._widgets.items():
            handler = getattr(widget, "on_state_changed", None)
            if handler is None:
                continue
            try:
                handler(change, snapshot)
            except Exception as exc:
                self._reporter.report(
                    AppError.from_exception(
                        exc, source="gui",
                        message="Tab '" + module_id + "' hat die Zustandsaenderung nicht verarbeitet: " + str(exc),
                        message_key="gui:state:" + module_id,
                    )
                )

    def widget_for(self, module_id: str) -> QWidget | None:
        return self._widgets.get(module_id)

    def shutdown(self) -> None:
        self._context.state.remove_listener(self._on_state_changed)
        for module_id, widget in self._widgets.items():
            handler = getattr(widget, "shutdown", None)
            if handler is None:
                continue
            try:
                handler()
            except Exception as exc:
                self._reporter.exception(exc, source="gui", module=module_id)
