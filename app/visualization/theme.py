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
app/gui/theme.py holt sich die Palette von hier und ergaenzt das
Stylesheet.

Bewusst ohne Qt-Import: reine Zeichenketten, in Stylesheets, QColor und
PyVista gleichermassen verwendbar.

Zwei Fassungen, hell und dunkel. Welche gilt, entscheidet die Einstellung von
Windows - abgefragt in app/core/os_theme.py, uebersteuerbar mit der
Umgebungsvariablen TRXING_THEME.

Die Entscheidung faellt EINMAL beim Import und gilt fuer den ganzen Lauf. Der
Grund ist die Verwendung: ein Dutzend Module holt sich beim Import
`from ... import PALETTE` und haelt die Palette danach als Objekt fest. Wuerde
die Anwendung sie zur Laufzeit austauschen, sahen diese Module weiter die alte -
die Anzeige waere halb hell und halb dunkel. Ein Wechsel des Windows-Modus wirkt
deshalb beim naechsten Start, nicht im laufenden Fenster.

Die dunklen Werte sind auf die Qt-Palette in app/gui/theme.py abgestimmt:
Fensterfarbe 53,53,53, Eingabefelder 42,42,42, Auswahlfarbe 42,130,218. Beide
Stellen zeigen dieselben Farben, nur in verschiedener Schreibweise.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.os_theme import prefers_dark


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
