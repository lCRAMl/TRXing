"""Arbeit im Hintergrund: starten, abbrechen, Fortschritt melden.

Der Oberflaechen-Thread rechnet nicht (Spezifikation 07). Was hier steht, ist
alles, was dafuer noetig ist, und es gehoert zusammen:

    CancellationToken  der Abbruch, von aussen gesetzt, innen abgefragt
    RequestGate        welche Antwort noch gilt und welche ueberholt ist
    Job / FunctionJob  ein Lauf im Threadpool, mit Signalen nach aussen
    JobManager         die Pools und die laufenden Auftraege

Der Abbruch ist der Grund, warum es diesen Apparat ueberhaupt gibt. Die
Palettierung kann mit CP-SAT rechnen, und das ist der einzige wirklich lange
Lauf im Programm - er muss sich abbrechen lassen, ohne das Fenster
einzufrieren.

Zusammengelegt aus core/cancellation.py, core/requests.py und jobs/*.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable
import time
from enum import Enum
from typing import Any, Callable
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from app.fehler import AppError, ErrorReporter, Severity
import os
from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal
from app.fehler import ErrorReporter


# ---------------------------------------------------------------------------
# cancellation.py
# ---------------------------------------------------------------------------
"""Kooperativer Abbruch laufender Berechnungen.

Python-Threads lassen sich nicht praeemptiv beenden, deshalb pruefen lange
Schleifen das Token selbst. Tokens sind verkettbar: bricht ein Elterntoken ab,
nimmt es seine Kinder mit. Die Palettierung nutzt das, wenn ein Durchlauf
mehrere Musterkandidaten parallel bewertet.

Der Abbruch ist die eine Haelfte des Schutzes vor veralteten Ergebnissen, die
monoton steigende request_id in app/jobs/job_manager.py die andere: abgebrochen
wird, was noch laeuft - verworfen wird, was schon fertig ist, aber zu einer
ueberholten Anfrage gehoert.
"""

class CancelledError(Exception):
    """Wird von raise_if_cancelled geworfen und von der Jobhuelle als Abbruch gewertet."""


class CancellationToken:
    def __init__(self, parent: CancellationToken | None = None) -> None:
        self._event = threading.Event()
        self._parent = parent
        self._children: list[CancellationToken] = []
        self._lock = threading.Lock()
        if parent is not None:
            parent._attach(self)

    def _attach(self, child: CancellationToken) -> None:
        with self._lock:
            self._children.append(child)
        if self._event.is_set():
            child.cancel()

    @property
    def cancelled(self) -> bool:
        if self._event.is_set():
            return True
        return self._parent is not None and self._parent.cancelled

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            children = tuple(self._children)
        for child in children:
            child.cancel()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def child(self) -> CancellationToken:
        return CancellationToken(parent=self)


def never() -> CancellationToken:
    """Ein Token, das nie abgebrochen wird. Als Standardargument verwendbar."""
    return CancellationToken()


# ---------------------------------------------------------------------------
# requests.py
# ---------------------------------------------------------------------------
"""Schutz vor veralteten Ergebnissen (Spezifikation 08).

Das Problem: bei aktivem Debounce laufen mehrere Berechnungen zeitlich
ueberlappend. Sie kommen nicht zwangslaeufig in der Reihenfolge zurueck, in der
sie gestartet wurden - eine kleine Palette rechnet schneller als die grosse
davor. Ohne Gegenmassnahme ueberschreibt das Ergebnis der aelteren Anfrage die
Anzeige der neueren, und der Benutzer sieht Zahlen zu Eingaben, die er laengst
geaendert hat.

Die Loesung besteht aus zwei Teilen, die zusammengehoeren:

    CancellationToken   bricht ab, was noch laeuft
    RequestGate         verwirft, was schon fertig ist, aber ueberholt wurde

Der Abbruch allein genuegt nicht: zwischen "abgebrochen" und "Ergebnis liegt
bereits im Signalpuffer" gibt es ein Zeitfenster, das sich nicht schliessen
laesst. Die Torpruefung beim Empfang schliesst es.

Bewusst Qt-frei und ohne Threadbezug, damit die Regel ohne QApplication
pruefbar ist.
"""

@dataclass(frozen=True, slots=True)
class RequestTicket:
    """Ausweis einer Anfrage. Wandert mit dem Auftrag in den Worker und mit dem
    Ergebnis zurueck."""

    channel: str
    request_id: int
    state_revision: int = 0


class RequestGate:
    """Vergibt aufsteigende Nummern je Kanal und prueft zurueckkommende.

    Ein Kanal ist eine Anzeige, die genau ein aktuelles Ergebnis zeigt - etwa
    "pallet" oder "vacuum". Verschiedene Kanaele stoeren sich nicht.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._issued: dict[str, int] = {}
        self._accepted: dict[str, int] = {}

    def issue(self, channel: str, state_revision: int = 0) -> RequestTicket:
        """Neue, hoehere Nummer fuer diesen Kanal."""
        with self._lock:
            next_id = self._issued.get(channel, 0) + 1
            self._issued[channel] = next_id
            return RequestTicket(channel=channel, request_id=next_id, state_revision=state_revision)

    def is_current(self, ticket: RequestTicket) -> bool:
        """Ob dieses Ergebnis noch das juengste seines Kanals ist."""
        with self._lock:
            return self._issued.get(ticket.channel, 0) == ticket.request_id

    def accept(self, ticket: RequestTicket) -> bool:
        """Ergebnis annehmen, wenn es aktuell ist.

        Merkt sich zusaetzlich die zuletzt angenommene Nummer: trifft ein noch
        aelteres Ergebnis nachtraeglich ein, wird auch das verworfen, selbst
        wenn zwischenzeitlich keine neue Anfrage mehr gestellt wurde.
        """
        with self._lock:
            if self._issued.get(ticket.channel, 0) != ticket.request_id:
                return False
            if ticket.request_id <= self._accepted.get(ticket.channel, 0):
                return False
            self._accepted[ticket.channel] = ticket.request_id
            return True

    def latest(self, channel: str) -> int:
        with self._lock:
            return self._issued.get(channel, 0)

    def invalidate(self, channel: str) -> None:
        """Alle laufenden Anfragen dieses Kanals entwerten, ohne eine neue zu
        starten. Wird gebraucht, wenn die Eingabe ungueltig wird."""
        with self._lock:
            self._issued[channel] = self._issued.get(channel, 0) + 1


# ---------------------------------------------------------------------------
# job_types.py
# ---------------------------------------------------------------------------
"""Kleine Typen der Jobschicht, die bis in die Oberflaeche sichtbar sind.

Die Oberflaeche bekommt von einem Service niemals den Job selbst - sonst haette
sie Zugriff auf dessen Ausfuehrung und koennte an der Serviceschicht vorbei
arbeiten. Sie bekommt einen JobHandle: Auskunft ueber die Anfrage und die
Moeglichkeit, sie abzubrechen. Mehr braucht sie nicht.
"""

@dataclass(frozen=True, slots=True)
class JobHandle:
    """Rueckgabewert von calculate_async(). Enthaelt keinen Qt-Typ."""

    job_id: int
    ticket: RequestTicket
    title: str = ""
    _cancel: Callable[[], None] | None = None

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel()

    @property
    def request_id(self) -> int:
        return self.ticket.request_id

    @property
    def channel(self) -> str:
        return self.ticket.channel


#: Kanalnamen. Jeder Kanal zeigt genau ein aktuelles Ergebnis an.
CHANNEL_PALLET = "pallet"
CHANNEL_VACUUM = "vacuum"


# ---------------------------------------------------------------------------
# job.py
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# job_manager.py
# ---------------------------------------------------------------------------
"""Zentrale Jobverwaltung.

Zwei getrennte Pools statt eines gemeinsamen mit Prioritaeten. QThreadPool kennt
zwar einen Prioritaetsparameter, aber keine Unterbrechung: belegt ein langer
Palettierlauf alle Faeden, wartet die schnelle Vakuumrechnung, bis er fertig
ist - obwohl sie Millisekunden braucht.

    interactive  kurze Rechnungen, die an einer Eingabe haengen
    cpu          Optimierungslaeufe, duerfen den Rechner auslasten

Der cpu-Pool laesst absichtlich zwei Kerne frei. Auf der Zielmaschine bleibt die
Oberflaeche damit fluessig, auch waehrend eine grosse Palette rechnet.

Gruppen: Jobs desselben Kanals bilden eine Gruppe. Eine neue Anfrage bricht die
Gruppe ab, bevor sie startet - das ist die Abbruchhaelfte des Schutzes vor
veralteten Ergebnissen. Die Torpruefung in app/core/requests.py ist die andere.
"""

@dataclass(frozen=True, slots=True)
class PoolConfig:
    interactive: int = 2
    cpu: int = 0  # 0 = Kerne minus zwei

    def resolved_cpu(self) -> int:
        if self.cpu > 0:
            return self.cpu
        return max(2, (os.cpu_count() or 4) - 2)


class JobManager(QObject):
    """Startet Jobs, verfolgt ihren Zustand und meldet Sammelfortschritt.

    job_started(job_id, titel)
    job_progress(job_id, current, total, text)
    job_finished(job_id, zustand)
    activity_changed(anzahl_laufend, text)
    """

    job_started = pyqtSignal(int, str)
    job_progress = pyqtSignal(int, int, int, str)
    job_finished = pyqtSignal(int, str)
    activity_changed = pyqtSignal(int, str)

    def __init__(self, reporter: ErrorReporter, config: PoolConfig | None = None) -> None:
        super().__init__()
        self._reporter = reporter
        self._config = config or PoolConfig()
        self._lock = threading.RLock()
        self._active: dict[int, Job] = {}
        self._titles: dict[int, str] = {}
        self._groups: dict[str, set[int]] = {}
        self._completed = 0
        self._failed = 0
        self._cancelled = 0

        self._pools = {
            "interactive": self._make_pool(self._config.interactive),
            "cpu": self._make_pool(self._config.resolved_cpu()),
        }

    @staticmethod
    def _make_pool(threads: int) -> QThreadPool:
        pool = QThreadPool()
        pool.setMaxThreadCount(max(1, threads))
        # Verhindert, dass Qt bei voller Warteschlange zusaetzliche Faeden ueber
        # das Limit hinaus erzeugt.
        pool.setExpiryTimeout(30000)
        return pool

    # Starten ------------------------------------------------------------------

    def submit(self, job: Job, group: str | None = None, cancel_group: bool = True) -> Job:
        """Stellt einen Job in seinen Pool.

        cancel_group bricht vorher alle laufenden Jobs derselben Gruppe ab -
        der Regelfall, wenn eine neue Eingabe die alte Rechnung ueberholt.
        """
        key = group or job.ticket.channel or "default"
        if cancel_group:
            self.cancel_group(key)

        job.signals.started.connect(lambda job_id: self._on_started(job_id))
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(self._on_finished)

        with self._lock:
            self._active[job.job_id] = job
            self._titles[job.job_id] = job.title
            self._groups.setdefault(key, set()).add(job.job_id)

        pool = self._pools.get(job.pool, self._pools["cpu"])
        pool.start(job)
        self._emit_activity()
        return job

    # Abbrechen ----------------------------------------------------------------

    def cancel_group(self, group: str) -> int:
        """Bricht alle Jobs einer Gruppe ab. Gibt die Anzahl zurueck."""
        with self._lock:
            job_ids = tuple(self._groups.get(group, ()))
            jobs = [self._active[j] for j in job_ids if j in self._active]
        for job in jobs:
            job.token.cancel()
        return len(jobs)

    def cancel_all(self) -> int:
        with self._lock:
            jobs = tuple(self._active.values())
        for job in jobs:
            job.token.cancel()
        return len(jobs)

    def wait_for_done(self, timeout_ms: int = 5000) -> bool:
        """Wartet, bis beide Pools leer sind. Nur fuer Tests und das Beenden -
        niemals aus einem Signalhandler der Oberflaeche aufrufen."""
        return all(pool.waitForDone(timeout_ms) for pool in self._pools.values())

    # Zustand ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def counters(self) -> dict[str, int]:
        with self._lock:
            return {
                "aktiv": len(self._active),
                "fertig": self._completed,
                "fehlgeschlagen": self._failed,
                "abgebrochen": self._cancelled,
            }

    def pool_sizes(self) -> dict[str, int]:
        return {name: pool.maxThreadCount() for name, pool in self._pools.items()}

    # Signalweiterleitung ------------------------------------------------------

    def _on_started(self, job_id: int) -> None:
        with self._lock:
            title = self._titles.get(job_id, "Berechnung")
        self.job_started.emit(job_id, title)
        self._emit_activity()

    def _on_progress(self, job_id: int, current: int, total: int, text: str) -> None:
        self.job_progress.emit(job_id, current, total, text)

    def _on_finished(self, job_id: int, state: str) -> None:
        with self._lock:
            self._active.pop(job_id, None)
            self._titles.pop(job_id, None)
            for members in self._groups.values():
                members.discard(job_id)
            if state == JobState.DONE.value:
                self._completed += 1
            elif state == JobState.FAILED.value:
                self._failed += 1
            elif state == JobState.CANCELLED.value:
                self._cancelled += 1
        self.job_finished.emit(job_id, state)
        self._emit_activity()

    def _emit_activity(self) -> None:
        with self._lock:
            count = len(self._active)
            titles = tuple(self._titles.values())
        if count == 0:
            self.activity_changed.emit(0, "")
        elif count == 1:
            self.activity_changed.emit(1, titles[0] if titles else "Berechnung")
        else:
            self.activity_changed.emit(count, str(count) + " Berechnungen")
