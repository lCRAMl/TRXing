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

from __future__ import annotations

import threading


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
