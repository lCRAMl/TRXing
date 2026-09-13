"""Was sich die Oberflaeche zwischen zwei Starts merkt.

Fenstergroesse, zuletzt benutzter Tab, Aufteilung der Splitter. Alles davon ist
eine Entscheidung des Benutzers - er zieht den Griff dorthin, wo er ihn haben
will, und erwartet ihn beim naechsten Start dort wieder. Eine Vorgabe im
Quelltext ist nur der erste Vorschlag fuer den allerersten Start.

Gespeichert wird ueber QSettings, unter Windows also in der Registry unter

    HKEY_CURRENT_USER\\Software\\TRXing\\<Abschnitt>

Bewusst NICHT in config/: dort stehen die technischen Daten der Anlage, die
gepflegt und weitergegeben werden. Wie breit jemand seine Bedienspalte zieht,
gehoert zu seinem Rechner und hat in einer ausgelieferten Konfigurationsdatei
nichts verloren.

Wer die gemerkten Werte loswerden will, loescht den Schluessel - danach gelten
wieder die Vorgaben aus dem Quelltext.
"""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtCore import QByteArray, QSettings

from app import APP_SLUG


def store(section: str) -> QSettings:
    """Der Ablageort eines Fensters oder Tabs."""
    return QSettings(APP_SLUG, section)


def save_splitter(splitter, section: str, key: str = "splitter") -> None:
    """Merkt sich die Aufteilung eines Splitters."""
    store(section).setValue(key, splitter.saveState())


def restore_splitter(
    splitter, section: str, fallback: Sequence[int], key: str = "splitter"
) -> None:
    """Stellt die gemerkte Aufteilung wieder her, sonst die Vorgabe.

    saveState/restoreState statt der blossen Zahlen: der Zustand enthaelt auch,
    welche Seite zusammengeklappt ist, und Qt rechnet ihn auf die aktuelle
    Fensterbreite um. Zwei gespeicherte Bildpunktwerte waeren auf einem anderen
    Bildschirm falsch.

    Die Mindestbreiten der beiden Seiten gelten weiterhin - eine gemerkte
    Aufteilung kann also nichts abschneiden, was nicht auch von Hand
    abgeschnitten werden koennte.
    """
    state = store(section).value(key)
    if isinstance(state, QByteArray) and not state.isEmpty() and splitter.restoreState(state):
        return
    splitter.setSizes(list(fallback))
