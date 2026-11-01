r"""Was sich die Oberflaeche zwischen zwei Starts merkt.

Fenstergroesse, zuletzt benutzter Tab, Aufteilung der Splitter. Alles davon ist
eine Entscheidung des Benutzers - er zieht den Griff dorthin, wo er ihn haben
will, und erwartet ihn beim naechsten Start dort wieder. Eine Vorgabe im
Quelltext ist nur der erste Vorschlag fuer den allerersten Start.

Gespeichert wird ueber QSettings, unter Windows also in der Registry unter

    HKEY_CURRENT_USER\Software\TRXing\<Abschnitt>

Bewusst NICHT in config/: dort stehen die technischen Daten der Anlage, die
gepflegt und weitergegeben werden. Wie breit jemand seine Bedienspalte zieht,
gehoert zu seinem Rechner und hat in einer ausgelieferten Konfigurationsdatei
nichts verloren.

Wer die gemerkten Werte loswerden will, loescht den Schluessel - danach gelten
wieder die Vorgaben aus dem Quelltext.

Dieses Modul lag kurzzeitig in qt_controls_pyrs und ist am 2026-10-31 wieder
hierher zurueckgekommen. Es war dort das deutlichste Fremdstueck: eine
Widget-Sammlung bestimmt das Aussehen und haelt keinen Zustand. Dieses Modul
schreibt in die Registry, kennt einen Anwendungsnamen und musste von der
Anwendung eingerichtet werden - in der Bibliothek brauchte es dafuer eine
modulweite Variable und eine set_application()-Funktion. Hier steht statt
dessen einfach APP_SLUG, und beides entfaellt.
"""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QSplitter

from app import APP_SLUG


def store(section: str) -> QSettings:
    """Der Ablageort eines Fensters oder Tabs."""
    return QSettings(APP_SLUG, section)


def save_splitter(splitter: QSplitter, section: str, key: str = "splitter") -> None:
    """Merkt sich die Aufteilung eines Splitters."""
    store(section).setValue(key, splitter.saveState())


def fit_controls_column(
    splitter: QSplitter,
    scroll,
    controls,
    view_width: int,
    section: str,
    key: str = "splitter",
) -> int:
    """Die Bedienspalte so breit machen, wie ihr Inhalt sie macht.

    Drei Tabs brauchen genau dasselbe, und zwar aus zwei Gruenden in einem:

    * Eine Rollflaeche gibt die Mindestbreite ihres Inhalts nicht nach aussen
      weiter. Ohne diese Zeile laesst sich der Griff des Teilers so weit nach
      links ziehen, dass Beschriftungen und Werte abgeschnitten werden. Die
      Breite des senkrechten Rollbalkens kommt dazu, sonst fehlt genau sie,
      sobald er erscheint.
    * Dieselbe Zahl ist die Anfangsbreite. Eine feste Zahl waere bei jeder
      Formularaenderung wieder falsch - die alten 460 und 600 Bildpunkte
      waren am Formular von vorgestern gemessen.

    Zieht der Benutzer den Griff, gilt seine Aufteilung, auch beim naechsten
    Start. Zurueck kommt die gemessene Breite, damit ein Test sie nachsehen
    kann, ohne sie nachzurechnen.
    """
    breite = (controls.minimumSizeHint().width()
              + scroll.verticalScrollBar().sizeHint().width())
    scroll.setMinimumWidth(breite)
    restore_splitter(splitter, section, (breite, view_width), key=key)
    return breite


def restore_splitter(
    splitter: QSplitter,
    section: str,
    fallback: Sequence[int],
    key: str = "splitter",
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
    if (isinstance(state, QByteArray) and not state.isEmpty()
            and splitter.restoreState(state)):
        return
    splitter.setSizes(list(fallback))
