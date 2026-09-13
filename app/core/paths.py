"""Verzeichnisse der Anwendung.

Eine gepackte Anwendung liegt anderswo als der Quelltext: PyInstaller entpackt
sich nach sys._MEIPASS, und neben der Programmdatei darf nichts geschrieben
werden. Deshalb zwei getrennte Wurzeln:

    resource_dir()  mitgelieferte, schreibgeschuetzte Daten (config/*.json)
    user_data_dir() beschreibbarer Ort fuer Protokoll und Oberflaechenzustand

Die Konfiguration wird ausdruecklich nur gelesen. Sucht die Anwendung sie an
mehreren Orten, gewinnt der erste Treffer - so laesst sich im Quelltextbetrieb
ohne Installation arbeiten und im gepackten Betrieb trotzdem eine danebenliegende
config/ verwenden.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app import APP_SLUG


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Wurzel der mitgelieferten Daten."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent.parent


def config_search_paths() -> list[Path]:
    """Orte, an denen nach den Konfigurationsdateien gesucht wird, in dieser
    Reihenfolge: neben der Programmdatei, im Bundle, im Quelltextbaum."""
    candidates: list[Path] = []
    if is_frozen():
        candidates.append(Path(sys.executable).resolve().parent / "config")
    candidates.append(resource_dir() / "config")
    source_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(source_root / "config")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def config_dir() -> Path:
    """Erster Suchpfad, der tatsaechlich existiert - sonst der bevorzugte."""
    for path in config_search_paths():
        if path.is_dir():
            return path
    return config_search_paths()[0]


def user_data_dir() -> Path:
    """Beschreibbares Verzeichnis fuer Protokoll und Fensterzustand."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / APP_SLUG
    return Path.home() / ("." + APP_SLUG.lower())


def log_dir() -> Path:
    return user_data_dir() / "logs"


def ensure_dir(path: Path) -> Path:
    """Verzeichnis anlegen, falls noetig. Gibt es zurueck, damit sich Aufrufe
    verketten lassen."""
    path.mkdir(parents=True, exist_ok=True)
    return path
