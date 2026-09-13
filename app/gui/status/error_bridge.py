"""Bruecke vom Qt-freien ErrorReporter zu Qt-Signalen.

Der Reporter wird aus Worker-Threads aufgerufen. Widgets duerfen aber nur aus
dem Oberflaechen-Thread angefasst werden. Diese Senke nimmt die Meldung im
aufrufenden Thread entgegen und gibt sie als Qt-Signal weiter; die Verbindung
auf Empfaengerseite ist eine QueuedConnection und stellt sie in der
Ereignisschleife der Oberflaeche zu.

Damit bleibt die gesamte Fachschicht ohne Qt testbar, und trotzdem landet jede
Meldung sichtbar in der Statusleiste.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.errors import AppError, ErrorReporter


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
