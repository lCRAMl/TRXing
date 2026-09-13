"""Aufklappbare Problemliste.

Das Gegenstueck zur Statusleiste: dort steht die juengste Meldung, hier stehen
alle. Gleichartige Meldungen sind zusammengefasst und gezaehlt (siehe
ProblemStore) - ohne das waere die Liste nach einer Minute entprellter
Neuberechnung mit identischen Zeilen gefuellt.

Kein modaler Dialog: das Fenster bleibt bedienbar, waehrend die Liste offen ist.
Man will die Meldung lesen und gleichzeitig die Eingabe korrigieren, die sie
ausgeloest hat.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError, ErrorReporter, Severity
from app.gui.common.widgets import mono_font
from app.gui.theme import PALETTE

_COLORS = {
    Severity.INFO: PALETTE.text_muted,
    Severity.WARNING: PALETTE.warning,
    Severity.ERROR: PALETTE.error,
    Severity.CRITICAL: PALETTE.critical,
}


class ProblemPanel(QDialog):
    """Liste der aufgetretenen Probleme mit technischen Einzelheiten."""

    def __init__(self, reporter: ErrorReporter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reporter = reporter
        self.setWindowTitle("Probleme")
        self.setModal(False)
        self.resize(880, 440)

        layout = QVBoxLayout(self)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["Stufe", "Zeit", "Herkunft", "Meldung", "Anzahl"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        header = self._tree.header()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 2, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.currentItemChanged.connect(self._show_details)
        layout.addWidget(self._tree, stretch=3)

        layout.addWidget(QLabel("Technische Einzelheiten"))
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setFont(mono_font())
        layout.addWidget(self._details, stretch=2)

        buttons = QHBoxLayout()
        clear = QPushButton("Liste leeren")
        clear.clicked.connect(self._clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        # Qt liefert die Beschriftung seiner Standardknoepfe aus eigenen
        # Uebersetzungsdateien, die die Anwendung nicht mitnimmt - ohne diese
        # Zeile steht in einem sonst deutschen Fenster "Close".
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("Schliessen")
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        self.refresh()

    def refresh(self) -> None:
        """Liste neu aufbauen. Wird beim Oeffnen und bei jeder neuen Meldung
        aufgerufen, solange das Fenster sichtbar ist."""
        selected = self._tree.currentItem()
        selected_key = selected.data(0, Qt.ItemDataRole.UserRole).message_key if selected else None

        self._tree.clear()
        restore: QTreeWidgetItem | None = None
        for error, count in self._reporter.problems.entries():
            item = QTreeWidgetItem([
                error.severity.label,
                time.strftime("%H:%M:%S", time.localtime(error.timestamp)),
                error.source,
                error.message,
                str(count) if count > 1 else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, error)
            item.setToolTip(3, error.message)

            # Die Stufe traegt die Farbe, die uebrigen Spalten die des Themas.
            # Eine feste Schriftfarbe waere hier falsch: in der dunklen Fassung
            # stuende sonst Schwarz auf dunklem Grund.
            for column in range(1, 5):
                item.setForeground(column, self.palette().text())
            item.setForeground(0, QColor(_COLORS.get(error.severity, PALETTE.text)))
            self._tree.addTopLevelItem(item)
            if selected_key and error.message_key == selected_key:
                restore = item

        if restore is not None:
            self._tree.setCurrentItem(restore)
        elif self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def _show_details(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self._details.setPlainText("")
            return
        error: AppError = current.data(0, Qt.ItemDataRole.UserRole)
        lines = [
            "Herkunft : " + error.source,
            "Stufe    : " + error.severity.label,
            "Zeit     : " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(error.timestamp)),
            "Meldung  : " + error.message,
        ]
        if error.context:
            lines.append("Kontext  : " + ", ".join(str(k) + "=" + str(v) for k, v in error.context.items()))
        if error.technical_message:
            lines.extend(["", error.technical_message])
        self._details.setPlainText("\n".join(lines))

    def _clear(self) -> None:
        self._reporter.problems.clear()
        self.refresh()
