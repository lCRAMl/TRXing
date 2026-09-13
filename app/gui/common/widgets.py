"""Wiederverwendete Bedienelemente.

Hier liegen die Bausteine, die alle drei Tabs gleich aussehen lassen: ein
Zahlenfeld mit Einheit und Fehleranzeige, ein Ergebnisraster und das Band fuer
veraltete Ergebnisse.

Keiner dieser Bausteine rechnet. Das Zahlenfeld prueft nicht, ob eine Laenge
plausibel ist - es zeigt an, was die Validierung der Fachschicht gemeldet hat.
Der Unterschied entscheidet darueber, ob die Regel an einer Stelle steht oder in
jedem Formular noch einmal.
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

from app.gui.theme import MONO_FAMILY, PALETTE

#: Breite, mit der Hinweistexte umbrechen.
#:
#: Die Zahl bestimmt nicht das Aussehen, sondern die Hoehenschaetzung des
#: Formulars. Ein umbrechendes QLabel berechnet seine bevorzugte Hoehe fuer
#: genau die gesetzte Mindestbreite - bei 1 bricht Qt rechnerisch nach jedem
#: Wort um und meldet mehrere hundert Bildpunkte Hoehe. Das Formular reserviert
#: sie brav, und zwischen den Eingabefeldern klafft eine handbreite Luecke,
#: waehrend der Text darin in drei Zeilen steht.
#:
#: 240 ist schmal genug, um die Bedienspalte nicht aufzuziehen, und breit genug
#: fuer eine ehrliche Hoehenschaetzung. tests/test_ui_files.py prueft, dass
#: jeder Hinweis in einer Layoutdatei sie mitbringt.
NOTE_WRAP_WIDTH = 240


def mono_font(bold: bool = False, point_size: int = 0) -> QFont:
    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size:
        font.setPointSize(point_size)
    font.setBold(bold)
    return font


class NumberField(QWidget):
    """Zahleneingabe mit Einheit und Platz fuer eine Fehlermeldung.

    Die Meldung steht unter dem Feld statt in einem Dialog - Spezifikation 34
    verlangt die Anzeige direkt am Eingabefeld. Der Platz wird dauerhaft
    reserviert, sonst springt das ganze Formular, sobald ein Fehler erscheint
    oder verschwindet.
    """

    value_changed = pyqtSignal(float)

    def __init__(
        self,
        unit: str = "",
        *,
        minimum: float = 0.0,
        maximum: float = 1_000_000.0,
        decimals: int = 1,
        step: float = 1.0,
        value: float = 0.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin.setKeyboardTracking(True)
        self.spin.setFont(mono_font())
        self.spin.setMinimumWidth(110)
        self.spin.valueChanged.connect(self.value_changed.emit)
        row.addWidget(self.spin)

        self._unit = QLabel(unit)
        self._unit.setProperty("role", "unit")
        self._unit.setMinimumWidth(40)
        row.addWidget(self._unit)
        row.addStretch(1)
        layout.addLayout(row)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setMinimumHeight(14)
        font = self._message.font()
        font.setPointSize(max(7, font.pointSize() - 1))
        self._message.setFont(font)
        layout.addWidget(self._message)

        self._normal_style = self.spin.styleSheet()

    def configure(
        self,
        unit: str = "",
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        decimals: int | None = None,
        step: float | None = None,
        value: float | None = None,
        tooltip: str = "",
    ) -> "NumberField":
        """Setzt Einheit, Wertebereich und Schrittweite nachtraeglich.

        Gebraucht, seit das Layout aus einer .ui-Datei kommt: der Qt Designer
        legt das Feld an und bestimmt, wo es sitzt und wie seine Zeile heisst -
        was es bedeutet, steht hier. Einheit und Grenzen sind Fachwissen
        (Millimeter, 10 bis 3000), keine Gestaltung; in der XML-Datei laegen sie
        als namenlose Eigenschaften ohne jede Pruefung.

        Gibt sich selbst zurueck, damit sich Anlegen und Einstellen in einer
        Zeile lesen lassen.
        """
        if unit:
            self._unit.setText(unit)
        if decimals is not None:
            self.spin.setDecimals(decimals)
        if minimum is not None or maximum is not None:
            self.spin.setRange(
                self.spin.minimum() if minimum is None else minimum,
                self.spin.maximum() if maximum is None else maximum,
            )
        if step is not None:
            self.spin.setSingleStep(step)
        if value is not None:
            self.set_value(value)
        if tooltip:
            self.spin.setToolTip(tooltip)
        return self

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float) -> None:
        """Setzt den Wert, ohne value_changed auszuloesen.

        Noetig, wenn ein Tab ein Feld aus dem Zustand nachfuehrt - sonst
        entsteht eine Rueckkopplung zwischen Anzeige und Zustand.
        """
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)

    def set_error(self, message: str) -> None:
        self._message.setText(message)
        self._message.setStyleSheet("color: " + PALETTE.error + ";")
        self.spin.setStyleSheet("border: 1px solid " + PALETTE.error + ";")

    def set_warning(self, message: str) -> None:
        self._message.setText(message)
        self._message.setStyleSheet("color: " + PALETTE.warning + ";")
        self.spin.setStyleSheet("border: 1px solid " + PALETTE.warning + ";")

    def clear_message(self) -> None:
        self._message.setText("")
        self.spin.setStyleSheet(self._normal_style)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt-Namensschema
        super().setEnabled(enabled)
        self.spin.setEnabled(enabled)


class IntField(QWidget):
    """Ganzzahleingabe mit Einheit. Fuer Stueckzahlen."""

    value_changed = pyqtSignal(int)

    def __init__(
        self,
        unit: str = "",
        *,
        minimum: int = 0,
        maximum: int = 1_000_000,
        value: int = 0,
        special_zero_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin.setFont(mono_font())
        self.spin.setMinimumWidth(110)
        if special_zero_text:
            # Null bedeutet hier nicht "keine", sondern "automatisch". Ohne
            # Sondertext waere das aus der Anzeige nicht zu erkennen.
            self.spin.setSpecialValueText(special_zero_text)
        self.spin.valueChanged.connect(self.value_changed.emit)
        layout.addWidget(self.spin)

        self._unit = QLabel(unit)
        self._unit.setProperty("role", "unit")
        self._unit.setMinimumWidth(40)
        layout.addWidget(self._unit)
        layout.addStretch(1)

    def configure(
        self,
        unit: str = "",
        *,
        minimum: int | None = None,
        maximum: int | None = None,
        value: int | None = None,
        special_zero_text: str = "",
        tooltip: str = "",
    ) -> "IntField":
        """Setzt Einheit, Wertebereich und Sondertext nachtraeglich.

        Siehe NumberField.configure - dieselbe Aufgabenteilung zwischen
        .ui-Datei und Quelltext.
        """
        if unit:
            self._unit.setText(unit)
        if minimum is not None or maximum is not None:
            self.spin.setRange(
                self.spin.minimum() if minimum is None else minimum,
                self.spin.maximum() if maximum is None else maximum,
            )
        if value is not None:
            self.set_value(value)
        if special_zero_text:
            # Null bedeutet hier nicht "keine", sondern "automatisch". Ohne
            # Sondertext waere das aus der Anzeige nicht zu erkennen.
            self.spin.setSpecialValueText(special_zero_text)
        if tooltip:
            self.spin.setToolTip(tooltip)
        return self

    def value(self) -> int:
        return self.spin.value()

    def set_value(self, value: int) -> None:
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)

    def set_maximum(self, maximum: int) -> None:
        self.spin.setMaximum(max(self.spin.minimum(), maximum))


class ResultGrid(QGroupBox):
    """Beschriftete Ergebniswerte in zwei Spalten.

    Die Werte stehen in fester Laufweite und rechtsbuendig, damit Stellen
    untereinander stehen und sich zwei Rechenlaeufe vergleichen lassen.
    """

    def __init__(self, title: str = "Ergebnis", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(10, 14, 10, 10)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnStretch(1, 1)
        self._rows: dict[str, QLabel] = {}
        self._row_index = 0

    def add_row(self, key: str, label: str, value: str = "-") -> None:
        caption = QLabel(label)
        caption.setStyleSheet("color: " + PALETTE.text_muted + ";")
        display = QLabel(value)
        display.setFont(mono_font())
        display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        display.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._grid.addWidget(caption, self._row_index, 0)
        self._grid.addWidget(display, self._row_index, 1)
        self._rows[key] = display
        self._row_index += 1

    def add_separator(self) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: " + PALETTE.border + ";")
        self._grid.addWidget(line, self._row_index, 0, 1, 2)
        self._row_index += 1

    def set_value(self, key: str, value: str, color: str = "") -> None:
        label = self._rows.get(key)
        if label is None:
            return
        label.setText(value)
        label.setStyleSheet(("color: " + color + "; font-weight: 600;") if color else "")

    def clear_values(self, placeholder: str = "-") -> None:
        for label in self._rows.values():
            label.setText(placeholder)
            label.setStyleSheet("")

    def keys(self) -> tuple[str, ...]:
        return tuple(self._rows)


class StaleBanner(QFrame):
    """Hinweisband ueber einer veralteten Anzeige.

    Spezifikation 11: aendert sich das Paket, muessen abhaengige Tabs ihre
    Darstellung als veraltet erkennen. Das Ergebnis bleibt sichtbar - es war ja
    richtig, nur eben fuer andere Eingaben - und bekommt diesen Hinweis.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background: " + PALETTE.stale_background + "; border: 1px solid " + PALETTE.stale + ";"
            " border-radius: 2px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        self._label = QLabel("")
        self._label.setStyleSheet("color: " + PALETTE.stale + "; font-weight: 600;")
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.setVisible(False)

    def show_message(self, message: str) -> None:
        self._label.setText(message)
        self.setVisible(True)

    def hide_message(self) -> None:
        self.setVisible(False)


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
