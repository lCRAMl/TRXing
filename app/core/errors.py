"""Strukturierte Fehlerobjekte und deren Verteilung.

Vier Stufen:
    INFO      Hinweis, kein Eingriff noetig
    WARNING   eingeschraenktes Ergebnis, Anwendung weiter nutzbar
    ERROR     fehlgeschlagene Operation, System laeuft weiter
    CRITICAL  Kernkomponente nicht verfuegbar - Start nicht moeglich

Bewusst Qt-frei: der Reporter verteilt an registrierte Senken. Die Bruecke zu
Qt-Signalen liegt in app/gui/status/ und meldet sich dort an. Dadurch bleiben
Engines, Konfiguration und Jobs ohne QApplication testbar.

Eine fehlerhafte Senke darf die uebrigen nicht mitreissen - sonst reisst
ausgerechnet im Fehlerfall der Meldeweg ab. Jede Senke laeuft deshalb in ihrem
eigenen try-Block, und ihr eigenes Scheitern wird einmalig auf stderr vermerkt,
nicht erneut durch den Reporter geschickt.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Protocol


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40

    @property
    def label(self) -> str:
        return {
            Severity.INFO: "Hinweis",
            Severity.WARNING: "Warnung",
            Severity.ERROR: "Fehler",
            Severity.CRITICAL: "Kritisch",
        }[self]


@dataclass(frozen=True)
class AppError:
    """Ein Fehlerereignis. Unveraenderlich, damit es threadsicher wandern kann.

    message_key ist der Aggregationsschluessel: gleiche Fehlerart, wechselnde
    Details. Ohne ihn flutet eine ungueltige Eingabe bei aktivem Debounce die
    Problemliste mit hunderten gleichartigen Zeilen.
    """

    severity: Severity
    source: str
    message: str
    message_key: str = ""
    technical_message: str | None = None
    exception_type: str | None = None
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message_key:
            object.__setattr__(self, "message_key", self.source + ":" + self.message[:120])

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        source: str,
        severity: Severity = Severity.ERROR,
        message: str | None = None,
        message_key: str = "",
        **context: Any,
    ) -> AppError:
        return cls(
            severity=severity,
            source=source,
            message=message or (type(exc).__name__ + ": " + str(exc)),
            message_key=message_key or (source + ":" + type(exc).__name__),
            technical_message="".join(traceback.format_exception(exc)).rstrip(),
            exception_type=type(exc).__name__,
            context=context,
        )


class ErrorSink(Protocol):
    """Empfaenger fuer Fehlerereignisse. Muss threadsicher sein."""

    def handle(self, error: AppError) -> None: ...


#: Obergrenze des Problemspeichers. Reicht fuer eine Sitzung, verhindert aber,
#: dass eine Dauerschleife den Speicher fuellt.
MAX_STORED = 500


class ProblemStore:
    """Haelt die aufgetretenen Probleme fuer die Problemliste der Oberflaeche.

    Gleichartige Meldungen werden ueber message_key zusammengefasst und nur
    gezaehlt. Angezeigt wird das juengste Vorkommen.
    """

    def __init__(self, limit: int = MAX_STORED) -> None:
        self._limit = limit
        self._lock = threading.RLock()
        self._order: list[str] = []
        self._latest: dict[str, AppError] = {}
        self._counts: dict[str, int] = {}

    def handle(self, error: AppError) -> None:
        with self._lock:
            key = error.message_key
            if key not in self._latest:
                self._order.append(key)
                if len(self._order) > self._limit:
                    dropped = self._order.pop(0)
                    self._latest.pop(dropped, None)
                    self._counts.pop(dropped, None)
            self._latest[key] = error
            self._counts[key] = self._counts.get(key, 0) + 1

    def entries(self) -> list[tuple[AppError, int]]:
        """Juengste zuerst, mit Anzahl der Vorkommen."""
        with self._lock:
            return [(self._latest[k], self._counts[k]) for k in reversed(self._order) if k in self._latest]

    def count(self, minimum: Severity = Severity.WARNING) -> int:
        with self._lock:
            return sum(1 for k in self._order if self._latest[k].severity >= minimum)

    def clear(self) -> None:
        with self._lock:
            self._order.clear()
            self._latest.clear()
            self._counts.clear()


class ErrorReporter:
    """Zentrale Verteilstelle. Wird aus allen Threads aufgerufen."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sinks: list[ErrorSink] = []
        self._broken: set[int] = set()
        self.problems = ProblemStore()
        self.add_sink(self.problems)

    def add_sink(self, sink: ErrorSink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def remove_sink(self, sink: ErrorSink) -> None:
        with self._lock:
            if sink in self._sinks:
                self._sinks.remove(sink)

    def report(self, error: AppError) -> None:
        with self._lock:
            sinks = tuple(self._sinks)
        for sink in sinks:
            try:
                sink.handle(error)
            except Exception:
                # Die Senke selbst ist defekt. Ihr Scheitern darf weder die
                # uebrigen Senken noch den meldenden Aufrufer treffen - und es
                # darf nicht erneut durch report() laufen, sonst entsteht eine
                # Endlosschleife. Einmal auf stderr vermerken, dann stumm.
                ident = id(sink)
                if ident not in self._broken:
                    self._broken.add(ident)
                    print(
                        "Fehlersenke " + type(sink).__name__ + " ist ausgefallen:\n"
                        + traceback.format_exc(),
                        file=sys.stderr,
                    )

    # Bequemlichkeiten ---------------------------------------------------------

    def info(self, source: str, message: str, **context: Any) -> None:
        self.report(AppError(Severity.INFO, source, message, context=context))

    def warning(self, source: str, message: str, **context: Any) -> None:
        self.report(AppError(Severity.WARNING, source, message, context=context))

    def error(self, source: str, message: str, **context: Any) -> None:
        self.report(AppError(Severity.ERROR, source, message, context=context))

    def critical(self, source: str, message: str, **context: Any) -> None:
        self.report(AppError(Severity.CRITICAL, source, message, context=context))

    def exception(self, exc: BaseException, *, source: str, **context: Any) -> None:
        self.report(AppError.from_exception(exc, source=source, **context))


#: Signatur der Rueckrufe, mit denen sich Nicht-Qt-Code an Aenderungen haengt.
Listener = Callable[[AppError], None]


class CallbackSink:
    """Duennste moegliche Senke: leitet an eine Funktion weiter."""

    def __init__(self, callback: Listener) -> None:
        self._callback = callback

    def handle(self, error: AppError) -> None:
        self._callback(error)
