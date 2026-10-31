"""Wiederverwendbare Bedienelemente.

Was mehr als ein Tab braucht: die Entprellung, das Merken der Fenstergroesse
und ein paar Kleinigkeiten an Auswahlfeldern.

Die Formularteile - NumberField, IntField, ResultGrid, StaleBanner - stehen
seit dem Wechsel auf qt_controls_pyrs in der Bibliothek und werden hier nur
noch durchgereicht. Durchgereicht und nicht direkt importiert, weil die
.ui-Dateien sie unter `app.bedienelemente` suchen: der Qt Designer traegt den
Modulpfad in die XML-Datei ein, und der soll nicht an einer Bibliothek
haengen, die sich umbenennen laesst.

Zusammengelegt aus gui/common/widgets.py und gui/common/window_state.py.
"""

from __future__ import annotations

from typing import Callable
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from app.darstellung import MONO_FAMILY, PALETTE
from qt_controls_pyrs import (
    HaloButton, HaloCheckBox, HaloDoubleSpinBox, HaloDropdown, HaloGroupBox,
    HaloLineEdit, HaloRadioButton, HaloSpinBox, StaleBanner
)
from qt_controls_pyrs import IntField as _IntField
from qt_controls_pyrs import NumberField as _NumberField
from qt_controls_pyrs import ResultGrid as _ResultGrid
from typing import Sequence
from PyQt6.QtCore import QByteArray, QSettings
from app import APP_SLUG


# ---------------------------------------------------------------------------
# widgets.py
# ---------------------------------------------------------------------------
"""Wiederverwendete Bedienelemente.

Hier liegen die Bausteine, die alle drei Tabs gleich aussehen lassen: ein
Zahlenfeld mit Einheit und Fehleranzeige, ein Ergebnisraster und das Band fuer
veraltete Ergebnisse.

Keiner dieser Bausteine rechnet. Das Zahlenfeld prueft nicht, ob eine Laenge
plausibel ist - es zeigt an, was die Validierung der Fachschicht gemeldet hat.
Der Unterschied entscheidet darueber, ob die Regel an einer Stelle steht oder in
jedem Formular noch einmal.
"""

#: Durchgereicht aus der Bibliothek - siehe Dateikopf. Die Namen stehen
#: hier, damit die .ui-Dateien und die Tabs sie unveraendert finden.
__all__ = [
    "Debouncer", "IntField", "KompaktButton", "KompaktCheckBox",
    "KompaktDoubleSpinBox", "KompaktDropdown", "KompaktGroupBox",
    "KompaktLineEdit", "KompaktRadioButton", "KompaktSpinBox", "NumberField",
    "ResultGrid", "StaleBanner", "compact_combo", "mono_font",
    "restore_splitter", "save_splitter", "store",
]

# ---------------------------------------------------------------------------
# Kompakte Fassungen der Bedienelemente
# ---------------------------------------------------------------------------
"""Dichter als die Vorgaben der Bibliothek.

Die Bibliothek ist auf einzelne, grosszuegig gesetzte Bedienelemente
ausgelegt - 45 Pixel hohe Leisten mit 16 Pixel Luft ringsum. Ein
Berechnungsformular hat aber dreissig davon untereinander, und dann ist aus
Grosszuegigkeit Verschwendung geworden: die Bedienspalte laeuft nach unten aus
dem Fenster, und zwischen zwei Zeilen steht mehr Luft als Inhalt.

Geaendert werden deshalb nur Zahlen, nicht das Verhalten. Jede Klasse hier ist
ihr Vorbild aus der Bibliothek mit engeren Konstanten - der Halo-Schein bleibt,
er braucht nur weniger Platz.

    Hoehe einer Leiste    45 -> 26 Pixel
    Luftrand je Element   16 ->  2
    Textabstand innen     16 ->  8
    Abstand im Layout     18 ->  4

Die .ui-Dateien verweisen auf DIESE Klassen und nicht auf die der Bibliothek:
so steht die Dichte an einer Stelle und nicht in drei XML-Dateien.
"""

#: Hoehe einer Eingabeleiste. Die Schrift braucht rund 15 Pixel, der Rest ist
#: Luft ueber und unter ihr - weniger als 26 wirkt gedrueckt.
KOMPAKT_HOEHE = 26
KOMPAKT_RAND = 2          # Luft je Seite, in die der Schein hinauslaeuft
KOMPAKT_PAD = 8           # Abstand der Schrift zum Rahmen
KOMPAKT_ABSTAND = 4       # Abstand zwischen zwei Zeilen im Layout


class KompaktDropdown(HaloDropdown):
    """Auswahlfeld, eng gesetzt."""

    HEIGHT = KOMPAKT_HOEHE
    ROOM = KOMPAKT_RAND
    ROOM_Y = 1
    PAD = KOMPAKT_PAD


class KompaktLineEdit(HaloLineEdit):
    """Eingabefeld, eng gesetzt."""

    HEIGHT = KOMPAKT_HOEHE
    ROOM = KOMPAKT_RAND
    ROOM_Y = 1
    PAD = KOMPAKT_PAD


class _KompaktSpin:
    """Die engeren Masse beider Zahlenfelder, einmal aufgeschrieben.

    Auch die Pfeilspalte schrumpft mit: 26 Pixel waren auf eine 45 Pixel hohe
    Leiste gerechnet und saehen auf einer 26 Pixel hohen aus wie zwei Klötze.
    """

    HEIGHT = KOMPAKT_HOEHE
    ROOM = KOMPAKT_RAND
    ROOM_Y = 1
    PAD = KOMPAKT_PAD
    ARROW_ZONE = 16
    ARROW_W = 4
    ARROW_H = 3.0
    MIN_CHARS = 5


class KompaktSpinBox(_KompaktSpin, HaloSpinBox):
    """Ganzzahlfeld, eng gesetzt."""


class KompaktDoubleSpinBox(_KompaktSpin, HaloDoubleSpinBox):
    """Zahlenfeld mit Nachkommastellen, eng gesetzt."""


class KompaktGroupBox(HaloGroupBox):
    """Gruppenrahmen, eng gesetzt."""

    PAD_X = KOMPAKT_PAD
    PAD_TOP = 4
    PAD_BOTTOM = 8
    TITLE_LEFT = 10
    TITLE_PAD = 6


class KompaktButton(HaloButton):
    """Knopf, eng gesetzt."""

    HEIGHT = KOMPAKT_HOEHE
    PAD = 14


class KompaktCheckBox(HaloCheckBox):
    """Kaestchen, eng gesetzt und mit umbrechender Beschriftung.

    Der Umbruch ist hier kein Schoenheitsfehler, sondern noetig: eine Zeile wie
    "Teilweise aufliegende Sauger als tragend zaehlen" misst einzeilig ueber
    600 Bildpunkte und zwaenge die ganze Bedienspalte auf diese Breite - eine
    Rollflaeche gibt die Mindestbreite ihres Inhalts nach aussen weiter.
    """

    BOX = 13
    ROOM = 4
    GAP = 6
    WRAP_WIDTH = 240      # dieselbe Breite wie die Hinweistexte daneben


class KompaktRadioButton(HaloRadioButton):
    """Auswahlknopf, eng gesetzt."""

    RING = 13
    ROOM = 4
    GAP = 6
    CORE_PAD = 3.5


class NumberField(_NumberField):
    """Zahlenfeld mit Einheit, eng gesetzt."""

    SPIN = KompaktDoubleSpinBox
    MIN_WIDTH = 72
    UNIT_WIDTH = 28
    GAP = 4
    NOTE_HEIGHT = 12


class IntField(_IntField):
    """Stueckzahlfeld mit Einheit, eng gesetzt."""

    SPIN = KompaktSpinBox
    MIN_WIDTH = 72
    UNIT_WIDTH = 28
    GAP = 4


class ResultGrid(_ResultGrid):
    """Ergebniswerte, zweispaltig und eng gesetzt.

    Zweispaltig, weil der Block sonst nach unten aus der Spalte laeuft: die
    Palettierung zeigt zehn Werte, die Vakuumplatte sechzehn.
    """

    COLUMNS = 2
    SPACING_X = 10
    SPACING_Y = 2
    PAIR_GAP = 18
    PAD_X = KOMPAKT_PAD
    PAD_TOP = 4
    PAD_BOTTOM = 8
    TITLE_LEFT = 10
    TITLE_PAD = 6



class BreitesRaster(ResultGrid):
    """Ergebniswerte ueber die volle Breite, vierspaltig.

    Fuer den Platz unter der Zeichnung. Zweispaltig waere der Block dort
    sieben Zeilen hoch und nimmt der Zeichnung ein Drittel ihrer Hoehe -
    vierspaltig sind es vier, und die Zeichnung behaelt ihren Platz.
    """

    COLUMNS = 4


NOTE_WRAP_WIDTH = 240


def mono_font(bold: bool = False, point_size: int = 0) -> QFont:
    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size:
        font.setPointSize(point_size)
    font.setBold(bold)
    return font


class Debouncer:
    """Sammelt schnelle Aenderungen zu einem Aufruf (Spezifikation 32).

    Ohne diese Bremse startet jeder Tastendruck in einem Zahlenfeld einen
    eigenen Rechenlauf: aus "100", "1000", "10000" werden drei Optimierungen,
    von denen zwei sofort wieder verworfen werden.

    Kein QWidget, sondern ein Helfer um einen QTimer - dadurch ist er an kein
    Fenster gebunden und in jedem Tab gleich einsetzbar.
    """

    def __init__(self, callback: Callable[[], None], delay_ms: int = 200, parent: QWidget | None = None) -> None:
        self._callback = callback
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._fire)

    def trigger(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()

    def flush(self) -> None:
        """Sofort ausloesen, falls etwas aussteht - etwa beim Klick auf
        'Berechnen', damit die letzte Eingabe sicher drin ist."""
        if self._timer.isActive():
            self._timer.stop()
            self._fire()

    def _fire(self) -> None:
        self._callback()

    @property
    def pending(self) -> bool:
        return self._timer.isActive()


def compact_combo(combo, min_chars: int = 12, tooltip: str = ""):
    """Verhindert, dass ein langer Eintrag die ganze Spalte auseinanderzieht.

    QComboBox meldet als bevorzugte Breite die des laengsten Eintrags. Ein
    Eintrag wie "Rueckschlagventil (schliesst bei offenem Sauger)" macht damit
    das gesamte Formular so breit, dass es nicht mehr neben die Zeichenflaeche
    passt - und die Bedienspalte bekommt einen waagerechten Rollbalken.

    Die Breite wird deshalb auf eine feste Zeichenzahl begrenzt. Der
    vollstaendige Text bleibt beim Aufklappen sichtbar.

    Zum Tooltip: ohne eigenen Erklaerungstext zeigt er den gekuerzten Eintrag
    vollstaendig an und wird bei jedem Wechsel nachgefuehrt. Wird ein tooltip
    uebergeben, gilt dieser dauerhaft - eine Erklaerung, was die Auswahl
    bedeutet, ist mehr wert als die Wiederholung des sichtbaren Textes.

    Ein im Qt Designer hinterlegter Tooltip zaehlt als eigener Erklaerungstext.
    Ohne diese Ruecksicht wuerde der Aufruf ihn ueberschreiben, sobald das
    Auswahlfeld aus einer .ui-Datei stammt - und die Erklaerung waere genau
    dort verschwunden, wo sie jemand hingeschrieben hat.
    """
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(min_chars)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, combo.sizePolicy().verticalPolicy())

    tooltip = tooltip or combo.toolTip()
    if tooltip:
        combo.setToolTip(tooltip)
        return combo

    def _show_full_text(_index: int = 0) -> None:
        combo.setToolTip(combo.currentText())

    combo.currentIndexChanged.connect(_show_full_text)
    _show_full_text()
    return combo


# ---------------------------------------------------------------------------
# window_state.py
# ---------------------------------------------------------------------------
r"""Was sich die Oberflaeche zwischen zwei Starts merkt.

Fenstergroesse, zuletzt benutzter Tab, Aufteilung der Splitter. Alles davon ist
eine Entscheidung des Benutzers - er zieht den Griff dorthin, wo er ihn haben
will, und erwartet ihn beim naechsten Start dort wieder. Eine Vorgabe im
Quelltext ist nur der erste Vorschlag fuer den allerersten Start.

Gespeichert wird ueber QSettings, unter Windows also in der Registry unter

    HKEY_CURRENT_USER\Software\TRXing\<Abschnitt>

Bewusst NICHT in config/: dort stehen die technischen Daten der Anlage, die
gepflegt und weitergegeben werden. Wie breit jemand seine Bedienspalte zieht,
gehoert zu seinem Rechner und hat in einer ausgelieferten Konfigurationsdatei
nichts verloren.

Wer die gemerkten Werte loswerden will, loescht den Schluessel - danach gelten
wieder die Vorgaben aus dem Quelltext.
"""

def store(section: str) -> QSettings:
    """Der Ablageort eines Fensters oder Tabs."""
    return QSettings(APP_SLUG, section)


def save_splitter(splitter, section: str, key: str = "splitter") -> None:
    """Merkt sich die Aufteilung eines Splitters."""
    store(section).setValue(key, splitter.saveState())


def restore_splitter(
    splitter, section: str, fallback: Sequence[int], key: str = "splitter"
) -> None:
    """Stellt die gemerkte Aufteilung wieder her, sonst die Vorgabe.

    saveState/restoreState statt der blossen Zahlen: der Zustand enthaelt auch,
    welche Seite zusammengeklappt ist, und Qt rechnet ihn auf die aktuelle
    Fensterbreite um. Zwei gespeicherte Bildpunktwerte waeren auf einem anderen
    Bildschirm falsch.

    Die Mindestbreiten der beiden Seiten gelten weiterhin - eine gemerkte
    Aufteilung kann also nichts abschneiden, was nicht auch von Hand
    abgeschnitten werden koennte.
    """
    state = store(section).value(key)
    if isinstance(state, QByteArray) and not state.isEmpty() and splitter.restoreState(state):
        return
    splitter.setSizes(list(fallback))
