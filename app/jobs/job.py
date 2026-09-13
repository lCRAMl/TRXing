"""Basisklasse aller Hintergrundaufgaben.

Ein Job ist ein QRunnable mit eigenem Signalobjekt. Qt-Signale koennen nur von
einem QObject ausgehen, QRunnable ist keines - daher die Trennung in Job
(Ausfuehrung) und JobSignals (Benachrichtigung).

Die Verbindungen werden im Oberflaechen-Thread hergestellt und laufen als
QueuedConnection: die Zustellung passiert damit in der Ereignisschleife des
Empfaengers, nicht im Worker-Thread. Ohne das liefe Widget-Code im falschen
Thread, was Qt nicht erlaubt.

Jeder Job ist gekapselt: eine Ausnahme wird gefangen, gemeldet und als
failed-Signal zugestellt. Ein Fehler in einem Job darf weder andere Jobs noch
den Pool noch einen Tab mitnehmen (Spezifikation 09).
"""

from __future__ import annotations

import time
import threading
from enum import Enum
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.core.cancellation import CancellationToken, CancelledError
from app.core.errors import AppError, ErrorReporter, Severity
from app.core.requests import RequestTicket


class JobState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def label(self) -> str:
        return {
            JobState.PENDING: "wartend",
            JobState.RUNNING: "laeuft",
            JobState.DONE: "fertig",
            JobState.FAILED: "fehlgeschlagen",
            JobState.CANCELLED: "abgebrochen",
        }[self]


class JobSignals(QObject):
    """Signale eines einzelnen Jobs.

    started(job_id)
    progress(job_id, current, total, text)
    result(job_id, ticket, payload)
    failed(job_id, ticket, message)
    finished(job_id, zustand)
    """

    started = pyqtSignal(int)
    progress = pyqtSignal(int, int, int, str)
    result = pyqtSignal(int, object, object)
    failed = pyqtSignal(int, object, str)
    finished = pyqtSignal(int, str)


class Job(QRunnable):
    """Basisklasse. Unterklassen implementieren run_job()."""

    #: Pool, in dem der Job laufen soll: "interactive" oder "cpu".
    pool = "cpu"

    #: Anzeigename fuer Statusleiste und Protokoll.
    title = "Berechnung"

    _next_id = 0
    _id_lock = threading.Lock()

    def __init__(
        self,
        reporter: ErrorReporter,
        ticket: RequestTicket,
        token: CancellationToken | None = None,
    ) -> None:
        super().__init__()
        with Job._id_lock:
            Job._next_id += 1
            self.job_id = Job._next_id
        self.signals = JobSignals()
        self.ticket = ticket
        self.token = token or CancellationToken()
        self.state = JobState.PENDING
        self.started_at = 0.0
        self.duration_s = 0.0
        self._reporter = reporter
        self.setAutoDelete(True)

    # Von Unterklassen zu implementieren --------------------------------------

    def run_job(self) -> Any:
        raise NotImplementedError

    # Fortschritt --------------------------------------------------------------

    def report_progress(self, current: int, total: int, text: str = "") -> None:
        self.signals.progress.emit(self.job_id, current, total, text)

    # Ausfuehrung --------------------------------------------------------------

    def run(self) -> None:  # QRunnable
        if self.token.cancelled:
            self.state = JobState.CANCELLED
            self.signals.finished.emit(self.job_id, self.state.value)
            return

        self.state = JobState.RUNNING
        self.started_at = time.perf_counter()
        self.signals.started.emit(self.job_id)

        try:
            payload = self.run_job()
            if self.token.cancelled:
                self.state = JobState.CANCELLED
            else:
                self.state = JobState.DONE
                self.signals.result.emit(self.job_id, self.ticket, payload)
        except CancelledError:
            self.state = JobState.CANCELLED
        except Exception as exc:
            self.state = JobState.FAILED
            self._reporter.report(
                AppError.from_exception(
                    exc,
                    source=self.ticket.channel or "jobs",
                    severity=Severity.ERROR,
                    message=self.title + " fehlgeschlagen: " + type(exc).__name__ + ": " + str(exc),
                    message_key="job:" + self.ticket.channel + ":" + type(exc).__name__,
                    request_id=self.ticket.request_id,
                )
            )
            self.signals.failed.emit(self.job_id, self.ticket, str(exc))
        finally:
            self.duration_s = time.perf_counter() - self.started_at
            self.signals.finished.emit(self.job_id, self.state.value)


class FunctionJob(Job):
    """Job aus einer gewoehnlichen Funktion.

    Damit brauchen Services fuer jede Berechnung keine eigene Jobklasse. Die
    Funktion bekommt das Abbruchtoken und eine Fortschrittsmeldung uebergeben,
    bleibt aber selbst Qt-frei - sie wird direkt in den Engine-Tests
    mitgetestet.
    """

    def __init__(
        self,
        reporter: ErrorReporter,
        ticket: RequestTicket,
        function: Callable[..., Any],
        *,
        title: str = "Berechnung",
        pool: str = "cpu",
        token: CancellationToken | None = None,
    ) -> None:
        super().__init__(reporter, ticket, token)
        self._function = function
        self.title = title
        self.pool = pool

    def run_job(self) -> Any:
        return self._function(token=self.token, progress=self.report_progress)
