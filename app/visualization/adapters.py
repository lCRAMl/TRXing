"""Adapter fuer die 3D-Darstellung.

Spezifikation 12.6 verlangt, dass die 3D-Abhaengigkeit hinter einem Adapter
gekapselt ist, damit sie sich spaeter austauschen laesst. Der Vertrag steht
hier; die Umsetzung mit PyVista in pallet_3d.py.

Zwei Dinge erledigt der Adapter zusaetzlich:

* Er haelt VTK aus dem Startvorgang heraus. PyVista und VTK brauchen beim
  ersten Import spuerbar Zeit; der Import passiert deshalb erst, wenn jemand
  die 3D-Ansicht oeffnet. Wer nur palettiert und die Draufsicht benutzt,
  wartet nie darauf.
* Er faengt das Fehlen der Bibliothek ab. Ohne VTK zeigt der Tab einen
  Hinweistext statt zu scheitern - der Rest der Anwendung bleibt bedienbar.

Die Szene bekommt ausschliesslich das fertige PalletResult. Sie rechnet nichts
(Spezifikation 37).
"""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.dto.pallet import PalletResult
from app.visualization.theme import PALETTE


class Scene3D(Protocol):
    """Vertrag einer 3D-Ansicht."""

    def widget(self) -> QWidget: ...

    def set_result(self, result: PalletResult | None) -> None: ...

    def set_visible_layers(self, indices: set[int] | None) -> None: ...

    def set_stale(self, stale: bool) -> None: ...

    def reset_camera(self) -> None: ...

    def shutdown(self) -> None: ...


class MissingBackendScene:
    """Ersatzansicht, wenn keine 3D-Bibliothek verfuegbar ist."""

    def __init__(self, reason: str) -> None:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        label = QLabel(
            "Die 3D-Ansicht steht nicht zur Verfuegung.\n\n" + reason
            + "\n\nInstallation:  pip install pyvista pyvistaqt\n\n"
            "Die 2D-Draufsicht zeigt dieselben Daten."
        )
        label.setWordWrap(True)
        label.setStyleSheet("color: " + PALETTE.text_muted + "; padding: 30px;")
        layout.addWidget(label)
        layout.addStretch(1)

    def widget(self) -> QWidget:
        return self._widget

    def set_result(self, result: PalletResult | None) -> None:
        return None

    def set_visible_layers(self, indices: set[int] | None) -> None:
        return None

    def set_stale(self, stale: bool) -> None:
        return None

    def reset_camera(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


#: Was die 3D-Ansicht zum Laufen braucht.
#:
#: qtpy steht hier, obwohl keine Datei dieses Projekts es importiert: pyvistaqt
#: spricht ausschliesslich ueber qtpy mit Qt. Fehlt nur qtpy, meldete die
#: Pruefung frueher "alles da", und der Import in pallet_3d.py scheiterte eine
#: Zeile spaeter - der Tab riet dann zur Installation bereits installierter
#: Pakete. Genau so sah es im gepackten Programm aus, solange AUTOBUILD.py
#: qtpy ausgeschlossen hat.
_REQUIRED_MODULES = ("pyvista", "pyvistaqt", "qtpy")


def missing_modules() -> tuple[str, ...]:
    """Welche der noetigen Pakete fehlen, in der Reihenfolge von oben.

    Prueft nur die Importierbarkeit, ohne VTK tatsaechlich zu laden - der
    Import kostet spuerbar Zeit und gehoert nicht in den Startvorgang.
    """
    import importlib.util

    return tuple(name for name in _REQUIRED_MODULES if importlib.util.find_spec(name) is None)


def backend_available() -> bool:
    """Ob die 3D-Bibliothek vollstaendig installiert ist."""
    return not missing_modules()


def create_scene(parent: QWidget | None = None) -> Scene3D:
    """Erzeugt die 3D-Ansicht - oder die Ersatzansicht, wenn das nicht geht.

    Ein Fehler beim Aufbau darf den Tab nicht mitnehmen: die 3D-Ansicht ist ein
    Zusatz, die Berechnung und die Draufsicht sind der Kern.
    """
    missing = missing_modules()
    if missing:
        # Die fehlenden Pakete beim Namen nennen. Eine pauschale Meldung hat
        # die Fehlersuche frueher in die falsche Richtung geschickt.
        reason = (
            "Das Paket " + missing[0] + " ist nicht installiert."
            if len(missing) == 1
            else "Die Pakete " + ", ".join(missing) + " sind nicht installiert."
        )
        return MissingBackendScene(reason)
    try:
        from app.visualization.pallet_3d import PyVistaScene

        return PyVistaScene(parent)
    except Exception as exc:
        return MissingBackendScene(type(exc).__name__ + ": " + str(exc))
