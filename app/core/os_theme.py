"""Farbschema des Betriebssystems: helle oder dunkle Fenster.

Windows fuehrt die Einstellung "App-Modus" in der Registry. Sie steht dort als
AppsUseLightTheme unter

    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize

und ist 0 fuer dunkle, 1 fuer helle Fenster. Fehlt der Wert - auf aelteren
Windows-Fassungen oder auf einem anderen Betriebssystem -, gilt hell.

Warum die Registry und nicht QStyleHints.colorScheme(): die Abfrage muss VOR
der QApplication beantwortet sein. Die Farbpalette in
app/visualization/theme.py entscheidet beim Import, welche Werte gelten, und
sie darf Qt ausdruecklich nicht kennen (Spezifikation 10) - die Renderer und
die Engines sollen ohne Fenster testbar bleiben. Eine Registryabfrage aus der
Standardbibliothek erfuellt beides.

Die Umgebungsvariable TRXING_THEME sticht die Systemeinstellung:

    set TRXING_THEME=dark     immer dunkle Fenster
    set TRXING_THEME=light    immer helle Fenster
    set TRXING_THEME=auto     wie Windows (Vorgabe)

Damit laesst sich die dunkle Fassung auf einem hell eingestellten Rechner
ansehen - und der Test kann beide Faelle pruefen, ohne die Registry des
Benutzers anzufassen.
"""

from __future__ import annotations

import os

#: Name der Umgebungsvariablen, die die Systemeinstellung uebersteuert.
ENV_NAME = "TRXING_THEME"

_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_REGISTRY_VALUE = "AppsUseLightTheme"


def override() -> str:
    """Der Inhalt von TRXING_THEME, klein geschrieben. Leer, wenn nicht gesetzt."""
    return os.environ.get(ENV_NAME, "").strip().lower()


def windows_prefers_dark() -> bool:
    """Steht Windows auf dunkle Fenster?

    False auf jedem System ohne diesen Registrywert - auch bei einem Fehler
    beim Lesen. Ein nicht lesbarer Registryschluessel darf den Start nicht
    aufhalten; hell ist der unauffaellige Rueckfall.
    """
    try:
        import winreg
    except ImportError:
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATH) as key:
            value, _type = winreg.QueryValueEx(key, _REGISTRY_VALUE)
    except OSError:
        return False
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def prefers_dark() -> bool:
    """Gilt fuer diesen Lauf das dunkle Farbschema?"""
    setting = override()
    if setting in ("dark", "dunkel"):
        return True
    if setting in ("light", "hell"):
        return False
    return windows_prefers_dark()
