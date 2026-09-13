"""Einstiegspunkt fuer die gepackte Anwendung.

`python -m app` bleibt der Weg fuer die Arbeit am Quelltext. PyInstaller braucht
dagegen eine gewoehnliche Skriptdatei als Startpunkt - ein Paketaufruf mit -m
laesst sich nicht paketieren. Diese Datei ist genau das und sonst nichts.
"""

from __future__ import annotations

import multiprocessing
import sys

from app.__main__ import main

if __name__ == "__main__":
    # Ohne diesen Aufruf startet eine mit --onefile gepackte Anwendung sich
    # selbst erneut, sobald irgendetwas multiprocessing benutzt - jeder
    # Kindprozess entpackt das Archiv noch einmal und oeffnet ein weiteres
    # Fenster. CP-SAT und VTK bringen beides mit.
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
