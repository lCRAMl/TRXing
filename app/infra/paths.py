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


#: Die Projektwurzel, von dieser Datei aus gezaehlt.
#:
#: DREI parent, weil diese Datei in app/infra/ liegt: infra -> app ->
#: Projektwurzel. Die Zahl ist schon zweimal falsch gewesen. Beim Umzug aus
#: app/core/ nach app/ blieb sie bei drei stehen, die Suche landete eine Ebene
#: ueber dem Projekt, und die Anwendung startete mit Notfalldaten - sechs
#: Paletten und vierundzwanzig Sauger fehlten, ohne dass ein Test rot wurde.
#: Die uebrigen Tests haengen sich ihr eigenes Konfigurationsverzeichnis ein
#: und koennen es deshalb nicht bemerken.
#:
#: Seitdem gibt es test_the_real_configuration_directory_is_found_in_the_source_tree
#: in tests/test_config.py: der prueft den echten Pfad und nicht einen
#: eingehaengten. Zieht diese Datei wieder um, muss diese Zeile mit - der Test
#: sagt es dann sofort.
_PROJEKTWURZEL = Path(__file__).resolve().parent.parent.parent


def resource_dir() -> Path:
    """Wurzel der mitgelieferten Daten."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return _PROJEKTWURZEL


def config_search_paths() -> list[Path]:
    """Orte, an denen nach den Konfigurationsdateien gesucht wird, in dieser
    Reihenfolge: neben der Programmdatei, im Bundle, im Quelltextbaum."""
    candidates: list[Path] = []
    if is_frozen():
        candidates.append(Path(sys.executable).resolve().parent / "config")
    candidates.append(resource_dir() / "config")
    source_root = _PROJEKTWURZEL
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
