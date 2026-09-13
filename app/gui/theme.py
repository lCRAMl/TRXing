"""Stylesheet der Anwendung.

Die Farbwerte selbst stehen in app/visualization/theme.py - dort, wo auch die
Renderer sie holen. Hier steht nur, wie Qt sie anwendet. Die Palette wird
weitergereicht, damit die Bedienelemente einen Importpfad haben.

Zu den Rollen: die Layoutdateien im Qt Designer zeichnen ein Label nur noch mit
einer Eigenschaft role aus - "note" fuer einen Hinweistext, "unit" fuer eine
Einheit, "hint" fuer einen Erklaerungsabsatz. Wie das aussieht, entscheidet
ausschliesslich dieses Stylesheet.

Der Grund ist nicht Geschmack: schreibt man die Farbe in jede .ui-Datei, liegt
sie dreifach vor und ein Themenwechsel erwischt sie nicht. Im Designer stellt
man so ein, WAS ein Widget ist, nicht wie es aussieht.

Qt wertet Eigenschaftsselektoren wie QLabel[role="note"] beim Setzen des
Stylesheets aus. Wird die Rolle spaeter zur Laufzeit geaendert, muss der Stil
mit unpolish/polish neu angewandt werden - hier kommt sie aus der .ui-Datei und
steht damit vor dem ersten Anzeigen fest.

Dunkle Fenster
--------------

Steht Windows auf dunkle Fenster, gilt die dunkle Palette (entschieden in
app/visualization/theme.py, abgefragt in app/core/os_theme.py) und zusaetzlich
das Stylesheet aus darkstyle/. apply_theme() setzt das vor dem ersten Fenster.

Drei Teile greifen ineinander:

    QStyleFactory "Fusion"   der einzige Qt-Stil, der eine eigene Palette
                             vollstaendig durchreicht. Der Windows-Stil malt
                             Rahmen und Knoepfe mit Systemfarben und bliebe
                             hell.
    QPalette                 die Farben der Rollen - Fenster, Eingabefeld,
                             Auswahl. Sie wirkt auf alles, was kein Stylesheet
                             anfasst, und auf palette(...) im Stylesheet.
    darkstyle/darkstyle.qss  die Feinheiten, fuer die eine Palette nicht
                             reicht: Rollbalken, Menues, Ankreuzfelder,
                             Aufklapppfeile - samt der Bildchen daneben.

Die Bildchen liegen als .png neben der .qss und werden dort als :/darkstyle/...
angesprochen, also als Qt-Ressource. PyQt6 hat kein pyrcc mehr, mit dem sich
eine solche Ressource uebersetzen liesse; statt dessen wird der Praefix beim
Laden durch den echten Ordnerpfad ersetzt. Das Ergebnis ist dasselbe, und die
.qss bleibt unveraendert die Datei, die sie im Ursprungsprojekt war.

Das Fenster setzt sein eigenes Stylesheet (stylesheet()) zusaetzlich. Qt mischt
beide; bei gleicher Kennzeichnung gewinnt das naeher am Widget gesetzte. Die
darkstyle-Regeln fuellen also die Luecken, ohne die Gestaltung der Anwendung zu
ueberschreiben.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

from app.visualization.theme import DARK, LIGHT, MONO_FAMILY, PALETTE, Palette

__all__ = [
    "DARK", "LIGHT", "MONO_FAMILY", "PALETTE", "Palette",
    "apply_theme", "dark_palette", "dark_stylesheet", "darkstyle_dir", "stylesheet",
    "FONT_SIZE_OFFSET_PT",
]

#: Ordner mit darkstyle.qss und den zugehoerigen Bildchen.
DARKSTYLE_DIRNAME = "darkstyle"

#: Praefix, unter dem die .qss ihre Bildchen erwartet.
_RESOURCE_PREFIX = ":/" + DARKSTYLE_DIRNAME + "/"

#: Schriftgroesse der ganzen Anwendung, in Punkten gegenueber der
#: Windows-Vorgabe. ---> HIER STELLT MAN DIE GROESSE ALLER BEDIENELEMENTE EIN.
#:
#: Die Schrift bestimmt die Groesse fast alles Uebrigen: Zeilenhoehen,
#: Eingabefelder, Knoepfe und Rahmen richten sich nach ihr. Ein Punkt weniger
#: macht die Oberflaeche spuerbar kompakter, ohne dass eine einzige Groesse von
#: Hand nachgezogen werden muesste.
#:
#:      0   wie Windows es vorgibt (Vorgabe)
#:     -1   kompakter, mehr Inhalt je Bildschirmhoehe
#:      2   wie die Vorlage des darkstyle-Ordners es vorsah
#:
#: Die Zahl gilt fuer beide Fassungen. Dass die Vorlage die Schrift NUR im
#: Dunkeln vergroesserte, war schwer zu erklaeren: die Schriftgroesse hat mit
#: dem Farbschema nichts zu tun, und ein Wechsel des Windows-Modus aenderte
#: dadurch die Groesse der ganzen Oberflaeche.
FONT_SIZE_OFFSET_PT = 0

#: Kleinste Schriftgroesse, die ein negativer Offset noch uebriglaesst.
MIN_FONT_POINT_SIZE = 6


def stylesheet(palette: Palette = PALETTE) -> str:
    """Das Stylesheet der Anwendung."""
    return "\n".join([
        "QWidget { color: " + palette.text + "; }",
        "QMainWindow, QDialog { background: " + palette.background + "; }",
        "QTabWidget::pane { border: 1px solid " + palette.border + "; background: " + palette.surface + "; }",
        "QTabBar::tab { padding: 7px 18px; margin-right: 2px; border: 1px solid " + palette.border + ";"
        " border-bottom: none; background: " + palette.surface_alt + "; }",
        "QTabBar::tab:selected { background: " + palette.surface + "; font-weight: 600; }",
        "QGroupBox { border: 1px solid " + palette.border + "; border-radius: 3px; margin-top: 10px;"
        " background: " + palette.surface + "; }",
        "QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px;"
        " color: " + palette.text_muted + "; font-weight: 600; }",
        "QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { border: 1px solid " + palette.border + ";"
        " border-radius: 2px; padding: 3px 5px; background: " + palette.surface + "; }",
        "QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {"
        " border: 1px solid " + palette.accent + "; }",
        "QPushButton { border: 1px solid " + palette.border + "; border-radius: 2px; padding: 5px 14px;"
        " background: " + palette.surface_alt + "; }",
        "QPushButton:hover { background: " + palette.accent_soft + "; }",
        "QPushButton:default { border: 1px solid " + palette.accent + "; }",
        "QPushButton:disabled { color: " + palette.text_muted + "; }",
        "QStatusBar { background: " + palette.surface_alt + "; border-top: 1px solid " + palette.border + "; }",
        "QStatusBar::item { border: none; }",
        "QTableWidget, QTreeWidget { background: " + palette.surface + ";"
        " gridline-color: " + palette.border + "; }",
        "QHeaderView::section { background: " + palette.surface_alt + "; border: none;"
        " border-right: 1px solid " + palette.border + "; padding: 4px; font-weight: 600; }",

        # Rollen aus den Layoutdateien.
        'QLabel[role="note"] { color: ' + palette.text_muted + "; font-size: 8pt; }",
        'QLabel[role="unit"] { color: ' + palette.text_muted + "; }",
        'QLabel[role="hint"] { color: ' + palette.text_muted + "; }",
        'QLabel[role="caption"] { color: ' + palette.text_muted + "; }",
    ])


# Dunkle Fenster ---------------------------------------------------------------

def darkstyle_dir() -> Path:
    """Der Ordner darkstyle/ neben dieser Datei.

    Auch in der gepackten Fassung: PyInstaller legt die mitgelieferten Dateien
    unter demselben relativen Pfad ab (siehe --add-data in AUTOBUILD.py), und
    __file__ zeigt dort in das entpackte Verzeichnis.
    """
    return Path(__file__).resolve().parent / DARKSTYLE_DIRNAME


def dark_stylesheet() -> str:
    """darkstyle.qss mit Pfaden, die ohne uebersetzte Qt-Ressource funktionieren.

    Leer, wenn die Datei fehlt. Das ist kein Grund, den Start abzubrechen - die
    Anwendung ist dann dunkel, nur ohne die Feinheiten, und der Grund steht im
    Protokoll.
    """
    directory = darkstyle_dir()
    source = directory / "darkstyle.qss"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        logging.getLogger("app").warning("darkstyle.qss nicht gelesen (%s): %s", source, exc)
        return ""
    return text.replace(_RESOURCE_PREFIX, directory.as_posix() + "/")


def dark_palette(palette: Palette = DARK) -> QPalette:
    """Die Qt-Palette der dunklen Fassung.

    Dieselben Werte wie in app/visualization/theme.py, nur in der Schreibweise
    von Qt. Die Rollen, fuer die es dort keine Entsprechung gibt - Schatten,
    heller Warntext, die ausgegrauten Zustaende -, stehen hier.

    Ausgegraut ist ausdruecklich mitgefuehrt. Ohne die Disabled-Eintraege zeigt
    Fusion ein gesperrtes Feld in derselben Farbe wie ein bedienbares, und der
    Unterschied zwischen "hier steht nichts" und "hier ist nichts einstellbar"
    geht verloren.
    """
    disabled = QColor(127, 127, 127)
    dark = QPalette()

    dark.setColor(QPalette.ColorRole.Window, QColor(palette.background))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(palette.text))
    dark.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    dark.setColor(QPalette.ColorRole.Base, QColor(palette.surface))
    dark.setColor(QPalette.ColorRole.AlternateBase, QColor(palette.surface_alt))
    dark.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette.surface))
    dark.setColor(QPalette.ColorRole.ToolTipText, QColor(palette.text))
    dark.setColor(QPalette.ColorRole.Text, QColor(palette.text))
    dark.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    dark.setColor(QPalette.ColorRole.Dark, QColor(35, 35, 35))
    dark.setColor(QPalette.ColorRole.Shadow, QColor(20, 20, 20))
    dark.setColor(QPalette.ColorRole.Button, QColor(palette.background))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(palette.text))
    dark.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    dark.setColor(QPalette.ColorRole.BrightText, QColor(palette.error))
    dark.setColor(QPalette.ColorRole.Link, QColor(palette.accent))
    dark.setColor(QPalette.ColorRole.Highlight, QColor(palette.accent))
    dark.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(80, 80, 80))
    dark.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    dark.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled)
    return dark


def apply_theme(app: QApplication, palette: Palette = PALETTE) -> bool:
    """Richtet Schrift, Stil und Palette der Anwendung ein.

    Die Schriftgroesse (FONT_SIZE_OFFSET_PT) wird immer gesetzt, der Rest nur
    in der dunklen Fassung. Gibt zurueck, ob die dunkle Fassung gesetzt wurde. In der hellen Fassung
    bleibt alles, wie Windows es vorgibt - dort sind die Systemfarben schon die
    richtigen, und der Windows-Stil zeichnet naeher am uebrigen Betriebssystem
    als Fusion.

    Aufzurufen NACH der QApplication und VOR dem ersten Fenster: eine spaeter
    gesetzte Palette erreicht bereits erzeugte Widgets nur teilweise.
    """
    # Die Schriftgroesse haengt nicht am Farbschema, sie gilt fuer beide
    # Fassungen - deshalb vor der Abfrage darunter.
    if FONT_SIZE_OFFSET_PT:
        font = QFont(app.font())
        font.setPointSize(max(MIN_FONT_POINT_SIZE, font.pointSize() + FONT_SIZE_OFFSET_PT))
        app.setFont(font)

    if not palette.dark:
        return False

    # Sollte Fusion einmal fehlen, bleibt der Systemstil stehen. Das Ergebnis
    # ist dann uneinheitlich, aber bedienbar - setStyle(None) waere es nicht.
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    app.setPalette(dark_palette(palette))
    app.setStyleSheet(dark_stylesheet())
    return True
