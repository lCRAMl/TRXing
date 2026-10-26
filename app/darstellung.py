"""Wie das Programm aussieht: Farben, Stylesheet, hell und dunkel.

Die Entscheidung hell oder dunkel faellt EINMAL beim Import und gilt dann
ueberall - PALETTE unten ist die eine Quelle, aus der sich Oberflaeche und
Zeichnungen bedienen. Wuerde sie spaeter wechseln, stuenden Widgets und
Zeichnungen in verschiedenen Farbschemata nebeneinander.

Die Reihenfolge in dieser Datei ist nicht beliebig:

    1. prefers_dark()  liest die Einstellung des Betriebssystems
    2. Palette, LIGHT, DARK, PALETTE  die Farben selbst
    3. toned()         blasse Fuellungen, die in beiden Schemata tragen
    4. stylesheet(), apply_theme()  das Qt-Stylesheet darueber

Schritt 2 ruft Schritt 1 beim Import auf; die Reihenfolge ist also Pflicht.

Der Ordner darkstyle/ liegt NEBEN dieser Datei und wird ueber __file__
gefunden - im Quelltextbaum wie im entpackten Paket. Zieht diese Datei um,
muss der Ordner mit (siehe DATA_FILES in AUTOBUILD.py).

Zusammengelegt aus core/os_theme.py, visualization/theme.py,
visualization/colors.py und gui/theme.py.
"""

from __future__ import annotations

from enum import Enum
import os
from dataclasses import dataclass
from PyQt6.QtGui import QColor
import logging
from pathlib import Path
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory


# ---------------------------------------------------------------------------
# darstellung.py
# ---------------------------------------------------------------------------
r"""Farbschema des Betriebssystems: helle oder dunkle Fenster.

Windows fuehrt die Einstellung "App-Modus" in der Registry. Sie steht dort als
AppsUseLightTheme unter

    HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize

und ist 0 fuer dunkle, 1 fuer helle Fenster. Fehlt der Wert - auf aelteren
Windows-Fassungen oder auf einem anderen Betriebssystem -, gilt hell.

Warum die Registry und nicht QStyleHints.colorScheme(): die Abfrage muss VOR
der QApplication beantwortet sein. Die Farbpalette in
app/darstellung.py entscheidet beim Import, welche Werte gelten, und
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


# ---------------------------------------------------------------------------
# Welche Ansicht ein Tab zeigt
# ---------------------------------------------------------------------------
#
# Fruehere Heimat: dto/common.py. Eine Ansichtsumschaltung ist eine Frage der
# Darstellung und kein Datenobjekt.

class ViewMode(Enum):
    """Ansichtsumschaltung des Palettentabs."""

    TOP_2D = "2d"
    SCENE_3D = "3d"

    @property
    def label(self) -> str:
        return {ViewMode.TOP_2D: "2D Draufsicht", ViewMode.SCENE_3D: "3D Ansicht"}[self]


# ---------------------------------------------------------------------------
# theme.py
# ---------------------------------------------------------------------------
"""Farbpalette der Anwendung.

Ziel ist der Eindruck eines technischen Werkzeugs, nicht einer Web-Anwendung:
ruhige Graustufen, eine einzige Akzentfarbe, klare Statusfarben und
Zahlenausgaben in einer Schrift mit fester Laufweite. Zahlen, die sich bei jeder
Neuberechnung aendern, springen in einer Proportionalschrift hin und her; mit
fester Laufweite stehen die Stellen still und lassen sich vergleichen.

Alle Farben stehen hier und nirgends sonst. Ein Widget, das eine eigene
Farbkonstante mitbringt, faellt beim naechsten Stilwechsel durch das Raster.

Warum die Palette in der Darstellungsschicht liegt und nicht bei der
Oberflaeche: die 2D- und 3D-Renderer brauchen dieselben Farben wie die
Bedienelemente. Laege sie in app/gui, muesste app/visualization dorthin
zurueckgreifen - eine Abhaengigkeit entgegen der Datenflussrichtung, die
tests/test_architecture.py verbietet. So zeigt sie in eine Richtung:
app/darstellung.py holt sich die Palette von hier und ergaenzt das
Stylesheet.

Bewusst ohne Qt-Import: reine Zeichenketten, in Stylesheets, QColor und
PyVista gleichermassen verwendbar.

Zwei Fassungen, hell und dunkel. Welche gilt, entscheidet die Einstellung von
Windows - abgefragt in app/darstellung.py, uebersteuerbar mit der
Umgebungsvariablen TRXING_THEME.

Die Entscheidung faellt EINMAL beim Import und gilt fuer den ganzen Lauf. Der
Grund ist die Verwendung: ein Dutzend Module holt sich beim Import
`from ... import PALETTE` und haelt die Palette danach als Objekt fest. Wuerde
die Anwendung sie zur Laufzeit austauschen, sahen diese Module weiter die alte -
die Anzeige waere halb hell und halb dunkel. Ein Wechsel des Windows-Modus wirkt
deshalb beim naechsten Start, nicht im laufenden Fenster.

Die dunklen Werte sind auf die Qt-Palette in app/darstellung.py abgestimmt:
Fensterfarbe 53,53,53, Eingabefelder 42,42,42, Auswahlfarbe 42,130,218. Beide
Stellen zeigen dieselben Farben, nur in verschiedener Schreibweise.
"""

@dataclass(frozen=True)
class Palette:
    """Farbwerte als Zeichenketten, damit sie in Stylesheets passen."""

    background: str = "#f4f5f7"
    surface: str = "#ffffff"
    surface_alt: str = "#eceef1"
    border: str = "#c8ccd2"
    text: str = "#1d2126"
    text_muted: str = "#5b636d"
    accent: str = "#1f6feb"
    accent_soft: str = "#dbe7fb"

    ok: str = "#2e7d4f"
    warning: str = "#b8860b"
    error: str = "#c0392b"
    critical: str = "#8b1a10"
    stale: str = "#8a6d1f"
    stale_background: str = "#fdf6dd"

    #: Untergrund eines hervorgehobenen Absatzes in der Rechenweghilfe.
    warning_background: str = "#fdf6dd"
    error_background: str = "#fdeceb"

    #: Zeichenflaeche der 2D-Ansichten.
    canvas: str = "#fbfbfc"
    canvas_grid: str = "#e3e6ea"
    pallet_fill: str = "#d9c39a"
    pallet_edge: str = "#8a7550"
    package_fill: str = "#c8dcf0"
    package_edge: str = "#4a7ba7"
    package_rotated_fill: str = "#f0dcc8"
    package_rotated_edge: str = "#a7784a"
    plate_fill: str = "#e8eaed"
    plate_edge: str = "#7d858f"
    cup_sealed: str = "#2e7d4f"
    cup_partial: str = "#b8860b"
    cup_open: str = "#c0392b"

    #: Aussenkontur des Saugers unter Vakuum - nur der Platzbedarf, ohne Aussage
    #: ueber Dichtheit. Neutral gehalten, damit sie die Statusfarben nicht
    #: stoert, aber dunkel genug, um auf der Plattenflaeche sichtbar zu bleiben:
    #: an diesem Ring stossen zwei Sauger aneinander.
    cup_outline: str = "#6c7683"

    #: Ob diese Fassung die dunkle ist. Die Renderer brauchen es dort, wo die
    #: Richtung zaehlt statt der Farbe - eine Flaeche wird auf hellem Grund
    #: aufgehellt und auf dunklem abgedunkelt.
    dark: bool = False


#: Die helle Fassung. Vorgabe jedes Feldes oben.
LIGHT = Palette()

#: Die dunkle Fassung.
DARK = Palette(
    background="#353535",
    surface="#2a2a2a",
    surface_alt="#424242",
    border="#555b61",
    text="#e9ebee",
    text_muted="#a2a9b2",
    accent="#2a82da",
    accent_soft="#1f3b57",

    # Statusfarben heller als in der hellen Fassung: auf dunklem Grund traegt
    # nicht die Tiefe der Farbe, sondern ihre Leuchtkraft.
    ok="#4caf7a",
    warning="#d8a92a",
    error="#ef6a5a",
    critical="#ff8a78",
    stale="#d8b44a",
    stale_background="#3a3222",
    warning_background="#3a3222",
    error_background="#3a2422",

    canvas="#232629",
    canvas_grid="#343a40",
    pallet_fill="#6b5a3e",
    pallet_edge="#c0a877",
    package_fill="#2f4a63",
    package_edge="#86b4dc",
    package_rotated_fill="#63472f",
    package_rotated_edge="#dcae86",
    plate_fill="#33383d",
    plate_edge="#98a1ab",
    cup_sealed="#46b57a",
    cup_partial="#d8a92a",
    cup_open="#e8604f",
    cup_outline="#aeb6c0",
    dark=True,
)

#: Die Fassung dieses Laufs. Ob sie die dunkle ist, steht in PALETTE.dark -
#: eine zweite Abfragefunktion daneben waere nur ein weiterer Weg zu derselben
#: Auskunft.
PALETTE = DARK if prefers_dark() else LIGHT

#: Schrift fuer Zahlenausgaben.
MONO_FAMILY = "Consolas, 'DejaVu Sans Mono', monospace"


# ---------------------------------------------------------------------------
# colors.py
# ---------------------------------------------------------------------------
"""Farbabstufungen der Zeichnungen.

Eine blasse Fuellung soll ihre Bedeutung behalten, gleich ob die Anwendung hell
oder dunkel laeuft. "Blass" heisst dabei nicht "heller", sondern "naeher am
Hintergrund": auf weissem Grund wird aufgehellt, auf dunklem abgedunkelt. Mit
einem festen lighter() waere die dunkle Fassung voller greller Flecken, und der
Ring, der die Aussage traegt, ginge daneben unter.

Die Richtung steckt in der Palette (Palette.dark) und damit an derselben
Stelle wie die Farben selbst - die Renderer fragen nicht, welches Farbschema
gilt.
"""

def toned(color: QColor | str, amount: int = 170) -> QColor:
    """Blassere Fassung einer Farbe, in Richtung des Hintergrunds.

    amount ist der Faktor von QColor.lighter()/darker() in Prozent: 100 laesst
    die Farbe unveraendert, 180 rueckt sie deutlich an den Hintergrund heran.
    """
    base = color if isinstance(color, QColor) else QColor(color)
    return base.darker(amount) if PALETTE.dark else base.lighter(amount)


# ---------------------------------------------------------------------------
# theme.py
# ---------------------------------------------------------------------------
"""Stylesheet der Anwendung.

Die Farbwerte selbst stehen in app/darstellung.py - dort, wo auch die
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
app/darstellung.py, abgefragt in app/darstellung.py) und zusaetzlich
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

    Dieselben Werte wie in app/darstellung.py, nur in der Schreibweise
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
