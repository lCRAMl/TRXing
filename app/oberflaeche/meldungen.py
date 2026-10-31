"""Wie Meldungen den Benutzer erreichen.

Drei Wege fuer dieselbe Sache: die Statuszeile zeigt die letzte Meldung, die
Problemliste alle, und die Bruecke bringt sie aus fremden Threads in den
Oberflaechen-Thread.

Zusammengelegt aus gui/status/{status_bar,problem_panel,error_bridge}.py.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QStatusBar, QWidget
from app.technik.fehler import AppError, Severity
from app.oberflaeche.darstellung import PALETTE
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
from app.technik.fehler import AppError, ErrorReporter, Severity
from app.oberflaeche.bedienelemente import LeistenKnopf, mono_font
from PyQt6.QtCore import QObject, pyqtSignal
from app.technik.fehler import AppError, ErrorReporter
from qt_controls_pyrs import HaloButton


# ---------------------------------------------------------------------------
# status_bar.py
# ---------------------------------------------------------------------------
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

Die Hoehe der Leiste ist die Hoehe ihres hoechsten Elements. Jeder Knopf darin
ist deshalb ein LeistenKnopf und kein gewoehnlicher - siehe dort, warum das
einmal anderthalb Zentimeter gekostet hat.

Hier steht auch der Abbruch. Gerechnet wird nach jeder Eingabe von selbst, ein
Knopf "Berechnen" waere also nur noch ein zweiter Weg zum selben Ergebnis; der
Abbruch dagegen bleibt noetig, weil ein Lauf mit dem zusaetzlichen Loeser lange
dauern kann. Er gehoert dorthin, wo auch steht, DASS gerechnet wird - und
zeigt sich nur dann.
"""

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
    """problems_clicked() - der Benutzer moechte die Problemliste sehen.

    cancel_requested() - der Benutzer moechte die laufende Berechnung stoppen.
    Die Leiste weiss nicht, welche das ist und bricht deshalb nichts selbst
    ab; sie meldet nur den Wunsch. Was daraus wird, entscheidet das Fenster.
    """

    problems_clicked = pyqtSignal()
    cancel_requested = pyqtSignal()

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
        self._progress.setFixedHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self.addPermanentWidget(self._progress)

        # Nur sichtbar, solange etwas laeuft. Ein dauerhaft sichtbarer, aber
        # gesperrter Abbruch beantwortet die Frage "laeuft gerade was?" falsch:
        # er sieht aus wie ein Bedienelement und ist meistens keines.
        self._cancel = LeistenKnopf("Abbrechen")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.setToolTip("Bricht die laufende Berechnung ab")
        self._cancel.setVisible(False)
        self._cancel.clicked.connect(self.cancel_requested.emit)
        self.addPermanentWidget(self._cancel)

        self._config = QLabel("")
        self._config.setStyleSheet("color: " + PALETTE.text_muted + ";")
        self.addPermanentWidget(self._config)

        self._problems = LeistenKnopf("Keine Probleme")
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
            self._cancel.setVisible(False)
            return
        elide(self._activity, text or "Berechnung laeuft", ACTIVITY_WIDTH)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # unbestimmt, bis Fortschritt kommt
        self._cancel.setVisible(True)

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


# ---------------------------------------------------------------------------
# problem_panel.py
# ---------------------------------------------------------------------------
"""Aufklappbare Problemliste.

Das Gegenstueck zur Statusleiste: dort steht die juengste Meldung, hier stehen
alle. Gleichartige Meldungen sind zusammengefasst und gezaehlt (siehe
ProblemStore) - ohne das waere die Liste nach einer Minute entprellter
Neuberechnung mit identischen Zeilen gefuellt.

Kein modaler Dialog: das Fenster bleibt bedienbar, waehrend die Liste offen ist.
Man will die Meldung lesen und gleichzeitig die Eingabe korrigieren, die sie
ausgeloest hat.
"""

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
        clear = HaloButton("Liste leeren")
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


# ---------------------------------------------------------------------------
# error_bridge.py
# ---------------------------------------------------------------------------
"""Bruecke vom Qt-freien ErrorReporter zu Qt-Signalen.

Der Reporter wird aus Worker-Threads aufgerufen. Widgets duerfen aber nur aus
dem Oberflaechen-Thread angefasst werden. Diese Senke nimmt die Meldung im
aufrufenden Thread entgegen und gibt sie als Qt-Signal weiter; die Verbindung
auf Empfaengerseite ist eine QueuedConnection und stellt sie in der
Ereignisschleife der Oberflaeche zu.

Damit bleibt die gesamte Fachschicht ohne Qt testbar, und trotzdem landet jede
Meldung sichtbar in der Statusleiste.
"""

class ErrorBridge(QObject):
    """error_reported(AppError)"""

    error_reported = pyqtSignal(object)

    def __init__(self, reporter: ErrorReporter, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reporter = reporter
        reporter.add_sink(self)

    def handle(self, error: AppError) -> None:  # ErrorSink
        self.error_reported.emit(error)

    def detach(self) -> None:
        self._reporter.remove_sink(self)
