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
Palettierung (app/gui/package/package_form.py) und schreibt in den
Anwendungszustand, aus dem sich jedes Modul bedient.

Warum dieser Vertrag in der Oberflaechenschicht liegt und nicht bei den
Services: er liefert ein QWidget. Damit ist er ein Belang der Oberflaeche. Die
Serviceschicht bleibt dadurch frei von QtWidgets, was die Architekturpruefung
erzwingen kann - eine schaerfere Trennung, als sie der Entwurf verlangt.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PyQt6.QtWidgets import QWidget

from app.services.context import AppContext


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
    from app.gui.pallet.pallet_tab import PalletModule
    from app.gui.vacuum.vacuum_tab import VacuumModule

    return [PalletModule(), VacuumModule()]
