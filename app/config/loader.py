"""Rohes Einlesen der Konfigurationsdateien.

Die einzige Stelle im Programm, die JSON-Dateien oeffnet. Alles darueber
arbeitet mit den bereits geprueften Objekten aus schema.py.

Fehlertoleranz ist hier Programm (Spezifikation 27): eine fehlende oder
beschaedigte Datei darf den Start nicht verhindern. Sie wird gemeldet, und der
Aufrufer arbeitet mit den eingebauten Ausweichdaten weiter. Nur so bleibt die
Anwendung auch dann bedienbar, wenn jemand eine Datei beim Bearbeiten zerlegt
hat - und genau dann braucht man sie, um den Fehler zu sehen.

Schluessel, die mit einem Unterstrich beginnen, sind Kommentare. JSON kennt
keine, und ein Kommentarfeld ist die einzige Moeglichkeit, die Herkunft eines
Kennwerts in der Datei selbst festzuhalten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import AppError, ErrorReporter, Severity


@dataclass(frozen=True, slots=True)
class LoadedFile:
    """Was beim Lesen einer Konfigurationsdatei herauskam."""

    name: str
    path: Path | None
    data: dict[str, Any]
    ok: bool
    message: str = ""

    @property
    def used_fallback(self) -> bool:
        return not self.ok


def strip_comments(data: dict[str, Any]) -> dict[str, Any]:
    """Entfernt Kommentarschluessel rekursiv aus geladenen Daten."""
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        if isinstance(value, dict):
            cleaned[key] = strip_comments(value)
        elif isinstance(value, list):
            cleaned[key] = [strip_comments(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


class ConfigLoader:
    """Liest die Konfigurationsdateien eines Verzeichnisses."""

    def __init__(self, directory: Path, reporter: ErrorReporter) -> None:
        self.directory = directory
        self._reporter = reporter

    def load(self, filename: str) -> LoadedFile:
        path = self.directory / filename

        if not path.is_file():
            message = "Konfigurationsdatei fehlt: " + str(path)
            self._reporter.report(
                AppError(
                    Severity.WARNING, "config", message,
                    message_key="config:missing:" + filename,
                    technical_message="Es werden die eingebauten Vorgabewerte verwendet.",
                )
            )
            return LoadedFile(filename, None, {}, ok=False, message=message)

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            message = "Konfigurationsdatei nicht lesbar: " + str(path)
            self._reporter.report(
                AppError.from_exception(
                    exc, source="config", severity=Severity.WARNING,
                    message=message, message_key="config:unreadable:" + filename,
                )
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            message = (
                "Konfigurationsdatei " + filename + " ist kein gueltiges JSON "
                "(Zeile " + str(exc.lineno) + ", Spalte " + str(exc.colno) + "): " + exc.msg
            )
            self._reporter.report(
                AppError(
                    Severity.ERROR, "config", message,
                    message_key="config:invalid:" + filename,
                    technical_message=str(path),
                )
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        if not isinstance(data, dict):
            message = "Konfigurationsdatei " + filename + " enthaelt kein Objekt auf oberster Ebene"
            self._reporter.report(
                AppError(Severity.ERROR, "config", message, message_key="config:shape:" + filename)
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        return LoadedFile(filename, path, strip_comments(data), ok=True)
