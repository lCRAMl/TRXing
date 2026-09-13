"""Gemeinsame Mechanik aller rechnenden Services.

Jeder Rechenservice macht dasselbe: Anfragenummer ziehen, Job bauen, in den
Pool geben, beim Eintreffen des Ergebnisses die Nummer pruefen und nur das
aktuelle Ergebnis weitergeben. Steht das nur einmal hier, kann ein neues
Berechnungsmodul es erben, statt es abzuschreiben - und der Schutz vor
veralteten Ergebnissen kann nicht in einem Modul vergessen werden.

Die Oberflaeche verbindet sich mit den Signalen dieser Klasse. Sie sieht weder
den Job noch die Engine (Spezifikation 29).

Zur Schichtregel: hier wird QtCore benutzt, aber kein QtWidgets und kein
app.gui. Signale sind der einzige threadsichere Weg, ein Ergebnis aus dem Worker
in die Oberflaeche zu bringen; Bedienelemente kennt die Serviceschicht nicht.
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.cancellation import CancellationToken
from app.core.errors import ErrorReporter
from app.core.requests import RequestGate, RequestTicket
from app.jobs.job import FunctionJob
from app.jobs.job_manager import JobManager
from app.jobs.job_types import JobHandle


class CalculationService(QObject):
    """Basis fuer Services, die asynchron rechnen.

    started(ticket)
    progress(current, total, text)
    result_ready(ergebnis)        nur fuer die aktuelle Anfrage
    failed(meldung)               nur fuer die aktuelle Anfrage
    superseded(request_id)        ein ueberholtes Ergebnis wurde verworfen
    """

    started = pyqtSignal(object)
    progress = pyqtSignal(int, int, str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    superseded = pyqtSignal(int)

    #: Kanalname - zugleich die Gruppe im JobManager.
    channel = "calculation"

    #: Anzeigename der Berechnung in der Statusleiste.
    job_title = "Berechnung"

    #: Pool, in dem gerechnet wird.
    pool = "cpu"

    def __init__(
        self,
        jobs: JobManager,
        gate: RequestGate,
        reporter: ErrorReporter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._gate = gate
        self._reporter = reporter

    # Fuer Unterklassen --------------------------------------------------------

    def _submit(
        self,
        work: Callable[..., Any],
        state_revision: int = 0,
        title: str | None = None,
    ) -> JobHandle:
        """Startet eine Berechnung.

        work bekommt token, progress und das Ticket uebergeben und gibt das
        Ergebnis zurueck. Es laeuft im Worker-Thread und darf deshalb nichts
        aus der Oberflaeche anfassen - was es auch nicht kann, da es nur die
        Engine kennt.
        """
        ticket = self._gate.issue(self.channel, state_revision)
        token = CancellationToken()

        def run(token: CancellationToken, progress) -> Any:
            return work(token=token, progress=progress, ticket=ticket)

        job = FunctionJob(
            self._reporter, ticket, run,
            title=title or self.job_title, pool=self.pool, token=token,
        )
        job.signals.result.connect(self._on_result)
        job.signals.failed.connect(self._on_failed)
        job.signals.progress.connect(
            lambda job_id, current, total, text: self.progress.emit(current, total, text)
        )

        self._jobs.submit(job, group=self.channel)
        self.started.emit(ticket)
        return JobHandle(job_id=job.job_id, ticket=ticket, title=job.title, _cancel=token.cancel)

    # Signalannahme ------------------------------------------------------------

    def _on_result(self, job_id: int, ticket: RequestTicket, payload: Any) -> None:
        """Die Torpruefung aus Spezifikation 08.

        Zwischen "abgebrochen" und "Ergebnis liegt schon im Signalpuffer" gibt
        es ein Zeitfenster, das sich nicht schliessen laesst. Hier wird es
        geschlossen: was nicht mehr aktuell ist, erreicht die Oberflaeche nicht.
        """
        if not self._gate.accept(ticket):
            self.superseded.emit(ticket.request_id)
            return
        self.result_ready.emit(payload)

    def _on_failed(self, job_id: int, ticket: RequestTicket, message: str) -> None:
        if not self._gate.accept(ticket):
            self.superseded.emit(ticket.request_id)
            return
        self.failed.emit(message)

    # Steuerung ----------------------------------------------------------------

    def cancel(self) -> None:
        """Bricht die laufende Berechnung dieses Kanals ab."""
        self._jobs.cancel_group(self.channel)

    def invalidate(self) -> None:
        """Entwertet laufende Anfragen, ohne eine neue zu starten.

        Gebraucht, wenn die Eingabe ungueltig wird: das Ergebnis waere zwar
        rechnerisch richtig, gehoert aber zu Zahlen, die nicht mehr gelten.
        """
        self._gate.invalidate(self.channel)
        self._jobs.cancel_group(self.channel)

    @property
    def current_request_id(self) -> int:
        return self._gate.latest(self.channel)
