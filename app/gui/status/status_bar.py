"""Statusleiste.

Spezifikation 09 verlangt ausdruecklich, normale Rechenfehler NICHT ueber
modale Dialoge zu zeigen. Ein Dialog unterbricht die Arbeit und erzwingt eine
Bestaetigung fuer etwas, das der Benutzer ohnehin gleich durch eine andere
Eingabe behebt - bei entprellter Neuberechnung kaeme er im Sekundentakt.

Stattdessen: eine dauerhafte Zustandsanzeige, die auf Klick die Problemliste
oeffnet, plus eine Fortschrittsanzeige fuer laufende Berechnungen.

Feste Breiten sind hier keine Kosmetik. Die Tatigkeitsanzeige nennt den Namen
der laufenden Berechnung, und die Namen sind unterschiedlich lang. Ohne feste
Breite verschiebt jeder Wechsel die Anzeigen daneben - die Leiste zappelt.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QStatusBar, QWidget

from app.core.errors import AppError, Severity
from app.gui.theme import PALETTE

#: Feste Breite der Tatigkeitsanzeige.
ACTIVITY_WIDTH = 260

#: Feste Breite der Meldungsanzeige.
MESSAGE_WIDTH = 420


def elide(label: QLabel, text: str, width: int) -> None:
    """Text auf die Breite kuerzen; vollstaendig bleibt er im Tooltip."""
    if not text:
        label.setText("")
        label.setToolTip("")
        return
    metrics = QFontMetrics(label.font())
    label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width - 8))
    label.setToolTip(text)


class StatusBar(QStatusBar):
    """problems_clicked() - der Benutzer moechte die Problemliste sehen."""

    problems_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._problem_count = 0

        self._message = QLabel("")
        self._message.setFixedWidth(MESSAGE_WIDTH)
        self.addWidget(self._message)

        self._activity = QLabel("")
        self._activity.setFixedWidth(ACTIVITY_WIDTH)
        self._activity.setStyleSheet("color: " + PALETTE.text_muted + ";")
        self.addPermanentWidget(self._activity)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(130)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self.addPermanentWidget(self._progress)

        self._config = QLabel("")
        self._config.setStyleSheet("color: " + PALETTE.text_muted + ";")
        self.addPermanentWidget(self._config)

        self._problems = QPushButton("Keine Probleme")
        self._problems.setFlat(True)
        self._problems.setCursor(Qt.CursorShape.PointingHandCursor)
        self._problems.clicked.connect(self.problems_clicked.emit)
        self.addPermanentWidget(self._problems)

    # Meldungen ----------------------------------------------------------------

    def show_status(self, text: str) -> None:
        self._message.setStyleSheet("")
        elide(self._message, text, MESSAGE_WIDTH)

    def show_error(self, error: AppError) -> None:
        """Zeigt die juengste Meldung. Nur ab Warnung aufwaerts - Hinweise
        wuerden die Leiste sonst dauerhaft belegen."""
        if error.severity < Severity.WARNING:
            return
        color = {
            Severity.WARNING: PALETTE.warning,
            Severity.ERROR: PALETTE.error,
            Severity.CRITICAL: PALETTE.critical,
        }.get(error.severity, PALETTE.text)
        self._message.setStyleSheet("color: " + color + ";")
        elide(self._message, error.severity.label + ": " + error.message, MESSAGE_WIDTH)

    def set_problem_count(self, count: int) -> None:
        self._problem_count = count
        if count == 0:
            self._problems.setText("Keine Probleme")
            self._problems.setStyleSheet("color: " + PALETTE.text_muted + ";")
        else:
            self._problems.setText(str(count) + (" Problem" if count == 1 else " Probleme"))
            self._problems.setStyleSheet("color: " + PALETTE.error + "; font-weight: 600;")

    # Aktivitaet ---------------------------------------------------------------

    def set_activity(self, count: int, text: str) -> None:
        if count <= 0:
            elide(self._activity, "", ACTIVITY_WIDTH)
            self._progress.setVisible(False)
            return
        elide(self._activity, text or "Berechnung laeuft", ACTIVITY_WIDTH)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # unbestimmt, bis Fortschritt kommt

    def set_progress(self, current: int, total: int, text: str = "") -> None:
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        if text:
            elide(self._activity, text, ACTIVITY_WIDTH)

    def set_config_info(self, text: str, tooltip: str = "") -> None:
        self._config.setText(text)
        self._config.setToolTip(tooltip)
