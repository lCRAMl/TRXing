"""Welche Rechenmodule es gibt - und wie daraus Tabs werden.

Das Hauptfenster kennt weder die Anzahl noch die Namen der Berechnungsmodule.
Es uebergibt Registry und Kontext, bekommt gefuellte Tabs zurueck und ist
fertig. Kein `if tab == 2` (Spezifikation 06).

Scheitert ein Modul beim Aufbau, bekommt es einen Platzhalter-Tab mit der
Fehlermeldung statt gar keinen. Sonst verschwindet das Modul kommentarlos aus
der Leiste, und niemand sucht den Grund an der richtigen Stelle.

Die Registry steht hier und nicht im Zusammenbau: sie beschreibt, WAS ein
Tab ist, und der TabManager daneben macht daraus einen. Lag sie in application.py,
musste tab_registry.py dorthin greifen und application.py wieder zurueck - ein Kreis.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from app.infra.errors import AppError, ErrorReporter, Severity
from app.gui.theme import PALETTE
from app.domain.state import AppStateSnapshot, StateChange
from app.context import AppContext


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


# ---------------------------------------------------------------------------
# module_registry.py
# ---------------------------------------------------------------------------
"""Der Modulvertrag und die Liste der registrierten Berechnungsmodule.

Spezifikation 06 verlangt, dass ein neues Berechnungsprogramm als Tab ergaenzt
werden kann, ohne Hauptfenster oder Kernarchitektur anzufassen. Der Vertrag ist
bewusst schmal:

    module_id      technische Kennung, auch Kanalname fuer Anfragenummern
    title          Beschriftung des Tabs
    order          Reihenfolge; gleiche Werte behalten die Eintragsreihenfolge
    create_widget  baut den Tab aus dem uebergebenen Kontext

Mehr braucht das Hauptfenster nicht zu wissen. Es gibt darin keine Abfrage auf
"Tab 1" oder "Tab 2", und kein Modul ist im Fenster namentlich erwaehnt.

Die Paketdaten sind bewusst KEIN Modul. Sie sind kein Berechnungsprogramm,
sondern die gemeinsame Eingabe aller Programme; ihr Formular sitzt am Kopf der
Palettierung (app/gui/pallet/form.py) und schreibt in den
Anwendungszustand, aus dem sich jedes Modul bedient.

Warum dieser Vertrag in der Oberflaechenschicht liegt und nicht bei den
Services: er liefert ein QWidget. Damit ist er ein Belang der Oberflaeche. Die
Serviceschicht bleibt dadurch frei von QtWidgets, was die Architekturpruefung
erzwingen kann - eine schaerfere Trennung, als sie der Entwurf verlangt.
"""

@runtime_checkable
class CalculationModule(Protocol):
    """Vertrag, den jedes Berechnungsmodul erfuellen muss."""

    module_id: str
    title: str
    order: int

    def create_widget(self, context: AppContext) -> QWidget: ...


class ModuleRegistry:
    """Haelt die registrierten Module in Anzeigereihenfolge."""

    def __init__(self) -> None:
        self._modules: list[CalculationModule] = []

    def register(self, module: CalculationModule) -> None:
        if not isinstance(module, CalculationModule):
            raise TypeError(
                type(module).__name__ + " erfuellt den Modulvertrag nicht "
                "(erwartet: module_id, title, order, create_widget)"
            )
        if any(existing.module_id == module.module_id for existing in self._modules):
            raise ValueError("Modulkennung '" + module.module_id + "' ist bereits vergeben")
        self._modules.append(module)

    def register_all(self, modules) -> None:
        for module in modules:
            self.register(module)

    def modules(self) -> tuple[CalculationModule, ...]:
        """Nach order sortiert; bei Gleichstand bleibt die Eintragsreihenfolge."""
        return tuple(sorted(self._modules, key=lambda m: m.order))

    def get(self, module_id: str) -> CalculationModule | None:
        return next((m for m in self._modules if m.module_id == module_id), None)

    def ids(self) -> tuple[str, ...]:
        return tuple(m.module_id for m in self.modules())

    def __len__(self) -> int:
        return len(self._modules)


def default_modules() -> list[CalculationModule]:
    """Die Module dieser Fassung.

    Ein weiteres Berechnungsprogramm wird hier angehaengt - eine Zeile, sonst
    nichts. Die Importe stehen absichtlich in der Funktion: so laedt der
    Modulvertrag ohne die Tabs, und Tests koennen ihn pruefen, ohne die ganze
    Oberflaeche zu bauen.
    """
    from app.gui.pallet.tab import PalletModule
    from app.gui.vacuum.tab import VacuumModule

    return [PalletModule(), VacuumModule()]
