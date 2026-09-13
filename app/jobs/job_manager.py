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

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from app.core.errors import ErrorReporter
from app.jobs.job import Job, JobState


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
