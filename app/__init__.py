"""Berechnungs-Suite: modular erweiterbare Sammlung technischer Rechenmodule.

Die Anwendung startet ueber `python -m app` (Quelltextbetrieb) oder ueber
main.py (gepackte Fassung). Die Schichtdisziplin ist in doc/ARCHITECTURE.md
beschrieben und wird von tests/test_architecture.py maschinell erzwungen.
"""

from __future__ import annotations

#: Anzeigename in Fenstertitel, Protokollkopf und Statusbericht.
APP_NAME = "TRXing"

#: Kurzname fuer Verzeichnisse und die gepackte Programmdatei.
APP_SLUG = "TRXing"

#: Version des Quelltextstandes. AUTOBUILD.py schreibt beim Paketieren
#: zusaetzlich build_version.py mit der aus Git ermittelten Fassung.
__version__ = "0.1.0"


def _build_info() -> tuple[str, str, str]:
    """(Version, Bauzeitpunkt, Commit) aus build_version.py, falls vorhanden.

    Im Quelltextbetrieb gibt es die Datei nicht - dann gilt die Version oben.
    Sie zu erzeugen ist Aufgabe des Bauskripts, nicht Voraussetzung fuer den
    Start.
    """
    try:
        import build_version
    except ImportError:
        return __version__, "", ""
    return (
        getattr(build_version, "VERSION", __version__),
        getattr(build_version, "BUILD_TIME", ""),
        getattr(build_version, "COMMIT", ""),
    )


def version_label() -> str:
    version, _build_time, _commit = _build_info()
    return APP_NAME + " " + version
