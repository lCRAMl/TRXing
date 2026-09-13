"""Das Programmsymbol.

Die .ico liegt hier und nicht im Wurzelverzeichnis, aus demselben Grund wie
darkstyle/ nebenan: sie gehoert der Oberflaeche, und wer sie sucht, sucht sie
bei der Oberflaeche. Beide Betriebsarten finden sie ueber __file__ - im
Quelltextbaum wie im entpackten Paket, wo PyInstaller sie unter demselben
relativen Pfad ablegt (siehe DATA_FILES in AUTOBUILD.py).

Zweimal wird sie gebraucht:

    zur Laufzeit    QApplication.setWindowIcon() - Titelleiste jedes Fensters
                    und jedes Dialogs
    beim Paketieren --icon fuer PyInstaller - das Symbol der .exe selbst, im
                    Explorer und in der Taskleiste

Das Datenformat ist Absicht: eine .ico traegt mehrere Aufloesungen in einer
Datei (16 bis 512 Bildpunkte). Windows greift sich die passende - fuer die
Titelleiste die kleine, fuer die grosse Kachelansicht des Explorers die grosse.
Ein einzelnes PNG saehe in einer der beiden Groessen ausgefranst aus.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QIcon

#: Dateiname des Programmsymbols.
APP_ICON_NAME = "pallet.ico"


def icon_dir() -> Path:
    """Der Ordner dieser Datei - dort liegen die Symbole."""
    return Path(__file__).resolve().parent


def app_icon_path() -> Path:
    """Pfad des Programmsymbols. AUTOBUILD.py gibt ihn an PyInstaller weiter."""
    return icon_dir() / APP_ICON_NAME


def app_icon() -> QIcon:
    """Das Programmsymbol.

    Ein leeres QIcon, wenn die Datei fehlt - Qt zeigt dann sein Standardsymbol.
    Ein fehlendes Bildchen ist kein Grund, den Start abzubrechen.
    """
    return QIcon(str(app_icon_path()))
