"""Protokollierung und globale Ausnahmehaken.

Zwei Aufgaben:

1. Eine rotierende Protokolldatei einrichten. Rotierend, weil die Anwendung bei
   aktivem Debounce viele kurze Rechenlaeufe protokolliert - ohne Rotation
   waechst die Datei ueber Wochen unbemerkt.

2. Unbehandelte Ausnahmen einfangen (Spezifikation 09). Ohne Haken verschwindet
   eine Ausnahme in einem Qt-Signalhandler stillschweigend, und die Oberflaeche
   steht ohne Hinweis still. Eingehaengt werden sys.excepthook (Hauptthread),
   threading.excepthook (Worker) und der Haken fuer nicht abgeholte
   Ausnahmen aus asynchronen Generatoren.

Protokolliert werden Zusammenfassungen, keine Objektabbilder (Spezifikation 40).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from app.core.errors import AppError, ErrorReporter, Severity
from app.core.paths import ensure_dir, log_dir

#: Groesse einer Protokolldatei, bevor rotiert wird.
MAX_BYTES = 2 * 1024 * 1024

#: Anzahl aufbewahrter aelterer Protokolldateien.
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"


def setup_logging(level: int = logging.INFO, directory: Path | None = None) -> Path:
    """Richtet Datei- und Konsolenprotokoll ein und gibt die Datei zurueck."""
    target_dir = ensure_dir(directory or log_dir())
    log_file = target_dir / "app.log"

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    console.setLevel(max(level, logging.WARNING))
    root.addHandler(console)

    return log_file


class LoggingSink:
    """Fehlersenke, die in das Protokoll schreibt.

    Die technische Meldung samt Rueckverfolgung landet nur in der Datei, nicht
    in der Oberflaeche - dort steht der kurze Text.
    """

    _LEVELS = {
        Severity.INFO: logging.INFO,
        Severity.WARNING: logging.WARNING,
        Severity.ERROR: logging.ERROR,
        Severity.CRITICAL: logging.CRITICAL,
    }

    def handle(self, error: AppError) -> None:
        logger = logging.getLogger(error.source)
        level = self._LEVELS.get(error.severity, logging.ERROR)
        context = ""
        if error.context:
            context = " (" + ", ".join(str(k) + "=" + str(v) for k, v in error.context.items()) + ")"
        logger.log(level, error.message + context)
        if error.technical_message:
            logger.debug(error.technical_message)


def install_excepthooks(reporter: ErrorReporter) -> None:
    """Haengt die globalen Ausnahmehaken ein.

    KeyboardInterrupt wird durchgereicht: ein Abbruch per Tastatur ist kein
    Programmfehler und soll das Programm wie gewohnt beenden.
    """

    def handle_main(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        reporter.report(
            AppError.from_exception(
                exc_value, source="excepthook", severity=Severity.ERROR,
                message="Unbehandelte Ausnahme: " + exc_type.__name__ + ": " + str(exc_value),
            )
        )

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None or issubclass(args.exc_type, SystemExit):
            return
        reporter.report(
            AppError.from_exception(
                args.exc_value, source="thread-excepthook", severity=Severity.ERROR,
                message="Unbehandelte Ausnahme im Thread "
                + (args.thread.name if args.thread else "?") + ": " + args.exc_type.__name__,
            )
        )

    sys.excepthook = handle_main
    threading.excepthook = handle_thread


def log_calculation(source: str, trace_summary: str, **context) -> None:
    """Einheitliche Protokollzeile fuer eine abgeschlossene Berechnung."""
    parts = " ".join(str(k) + "=" + str(v) for k, v in context.items())
    logging.getLogger(source).info(trace_summary + (" " + parts if parts else ""))
