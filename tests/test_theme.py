"""Tests des Farbschemas: helle und dunkle Fassung.

Drei Fragen stehen dahinter:

* Ist die dunkle Fassung vollstaendig? Eine vergessene Farbe faellt sonst erst
  auf, wenn jemand mit dunkel eingestelltem Windows den betroffenen Tab
  oeffnet - und zeigt sich dann als schwarze Schrift auf schwarzem Grund.
* Findet die Anwendung den Ordner darkstyle/ samt seiner Bildchen? Die .qss
  spricht sie als Qt-Ressource an; der Pfad wird beim Laden ersetzt.
* Hebt sich die Aussenkontur des Saugers von der Plattenflaeche ab? Sie ist der
  Ring, an dem zwei Sauger aneinanderstossen, und war zu blass, um ihn zu
  sehen.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QStyleFactory

from app.gui import theme
from app.visualization import colors
from app.visualization.theme import DARK, LIGHT, Palette

pytestmark = pytest.mark.usefixtures("qt_app")


def _relative_luminance(color: str) -> float:
    """Helligkeit nach WCAG, damit sich zwei Farben vergleichen lassen."""
    channels = []
    for value in QColor(color).getRgbF()[:3]:
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    a, b = _relative_luminance(first), _relative_luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


# Vollstaendigkeit -------------------------------------------------------------

@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["hell", "dunkel"])
def test_every_colour_is_a_valid_colour(palette: Palette):
    for field in fields(Palette):
        if field.type != "str":
            continue
        value = getattr(palette, field.name)
        assert QColor(value).isValid(), field.name + " ist keine Farbe: " + repr(value)


def test_the_two_fassungen_differ_in_every_colour():
    """Keine Farbe darf aus der hellen Fassung stehenbleiben.

    Ein uebersehener Wert ist genau der Fall, der spaeter als schwarze Schrift
    auf schwarzem Grund auffaellt.
    """
    unchanged = [
        field.name for field in fields(Palette)
        if field.type == "str" and getattr(LIGHT, field.name) == getattr(DARK, field.name)
    ]
    assert not unchanged, "in der dunklen Fassung unveraendert: " + ", ".join(unchanged)


def test_the_dark_fassung_is_marked_as_such():
    assert DARK.dark is True
    assert LIGHT.dark is False


def test_light_text_on_dark_ground_and_the_other_way_round():
    assert _contrast(LIGHT.text, LIGHT.background) >= 7.0
    assert _contrast(DARK.text, DARK.background) >= 7.0


# Sichtbarkeit der Saugerkontur ------------------------------------------------

@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["hell", "dunkel"])
def test_the_cup_outline_stands_out_from_the_plate(palette: Palette):
    """Spezifikation der Anzeige: man muss sehen, wo zwei Sauger anstossen.

    Die Kontur liegt auf der Plattenflaeche. Hebt sie sich davon kaum ab, ist
    sie zwar gezeichnet, aber nicht zu sehen - genau der Zustand, den diese
    Pruefung verhindert.
    """
    assert _contrast(palette.cup_outline, palette.plate_fill) >= 3.0


def test_the_outline_is_drawn_wherever_it_differs_from_the_sealing_ring():
    """Sie faellt nur weg, wenn sie ohnehin auf dem Dichtlippenring laege.

    Der Wirkungsbereich verschwindet frueher - drei Kreise dicht beieinander
    werden zu einem Fleck. Die Kontur ist der aeusserste und bleibt.
    """
    from app.visualization import vacuum_2d

    assert vacuum_2d.MIN_OUTLINE_GAP_PX <= 1.0
    assert vacuum_2d.OUTLINE_PEN_WIDTH >= 1.0


# Blasse Fuellungen ------------------------------------------------------------

def test_pale_fill_moves_towards_the_background(monkeypatch):
    """Blass heisst heller auf hellem Grund und dunkler auf dunklem.

    Mit einem festen lighter() waere die dunkle Fassung voller greller Flecken.
    """
    green = "#2e7d4f"

    monkeypatch.setattr(colors, "PALETTE", LIGHT)
    assert colors.toned(green, 170).lightness() > QColor(green).lightness()

    monkeypatch.setattr(colors, "PALETTE", DARK)
    assert colors.toned(green, 170).lightness() < QColor(green).lightness()


# Der Ordner darkstyle ---------------------------------------------------------

def test_the_darkstyle_folder_travels_with_the_gui():
    directory = theme.darkstyle_dir()
    assert directory.is_dir(), "darkstyle/ fehlt neben app/gui/theme.py"
    assert (directory / "darkstyle.qss").is_file()


def test_the_stylesheet_points_at_existing_images():
    """Die .qss spricht ihre Bildchen als Qt-Ressource an (:/darkstyle/...).

    PyQt6 hat kein pyrcc mehr, mit dem sich eine solche Ressource uebersetzen
    liesse - der Praefix wird beim Laden durch den Ordnerpfad ersetzt. Bleibt
    einer stehen, zeigt Qt kommentarlos gar kein Bild.
    """
    sheet = theme.dark_stylesheet()
    assert sheet, "darkstyle.qss wurde nicht gelesen"
    assert ":/" not in sheet

    referenced = re.findall(r"url\(([^)]+)\)", sheet)
    assert referenced, "keine Bildverweise gefunden - Vorlage veraendert?"
    missing = [path for path in referenced if not Path(path).is_file()]
    assert not missing, "Bilder fehlen: " + ", ".join(sorted(set(missing)))


def test_a_missing_folder_is_survivable(monkeypatch, tmp_path):
    """Ohne die Datei laeuft die Anwendung weiter, nur ohne die Feinheiten."""
    monkeypatch.setattr(theme, "darkstyle_dir", lambda: tmp_path / "gibtsnicht")
    assert theme.dark_stylesheet() == ""


# Anwenden ---------------------------------------------------------------------

def test_the_light_fassung_leaves_the_application_alone(qt_app):
    """Hell ist der Zustand, den Windows ohnehin vorgibt."""
    before = qt_app.styleSheet()
    assert theme.apply_theme(qt_app, LIGHT) is False
    assert qt_app.styleSheet() == before


def test_the_dark_fassung_sets_style_palette_and_stylesheet(qt_app):
    style_before = qt_app.style().name()
    font_before = QFont(qt_app.font())
    palette_before = QPalette(qt_app.palette())
    sheet_before = qt_app.styleSheet()
    try:
        assert theme.apply_theme(qt_app, DARK) is True

        assert qt_app.palette().color(QPalette.ColorRole.Window) == QColor(DARK.background)
        assert qt_app.palette().color(QPalette.ColorRole.Base) == QColor(DARK.surface)
        assert qt_app.font().pointSize() == (
            font_before.pointSize() + theme.FONT_SIZE_OFFSET_PT
        ), "Die Schriftgroesse folgt FONT_SIZE_OFFSET_PT"
        assert "QScrollBar" in qt_app.styleSheet()

        # Fusion ist der einzige Stil, der eine eigene Palette vollstaendig
        # durchreicht - mit dem Windows-Stil blieben Rahmen und Knoepfe hell.
        #
        # Solange ein Stylesheet gesetzt ist, liefert style() dessen Huelle
        # (QStyleSheetStyle) ohne Namen. Der darunterliegende Stil kommt erst
        # zum Vorschein, wenn das Stylesheet weg ist - und es wird hier ohnehin
        # gleich zurueckgesetzt.
        qt_app.setStyleSheet("")
        assert qt_app.style().name() == "fusion"
    finally:
        restored = QStyleFactory.create(style_before)
        if restored is not None:
            qt_app.setStyle(restored)
        qt_app.setFont(font_before)
        qt_app.setPalette(palette_before)
        qt_app.setStyleSheet(sheet_before)


def test_disabled_controls_stay_distinguishable():
    """Ohne die Disabled-Eintraege zeichnet Fusion ein gesperrtes Feld wie ein
    bedienbares - der Unterschied zwischen "leer" und "nicht einstellbar" geht
    verloren."""
    palette = theme.dark_palette(DARK)
    normal = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
    greyed = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert normal != greyed


def test_the_font_size_is_one_knob_for_both_fassungen(qt_app):
    """Die Schriftgroesse haengt nicht am Farbschema.

    Vorher wuchs sie nur in der dunklen Fassung: ein Wechsel des
    Windows-Modus aenderte damit die Groesse der ganzen Oberflaeche.
    """
    font_before = QFont(qt_app.font())
    try:
        theme.apply_theme(qt_app, LIGHT)
        light_size = qt_app.font().pointSize()
        qt_app.setFont(font_before)
        theme.apply_theme(qt_app, DARK)
        assert qt_app.font().pointSize() == light_size
    finally:
        qt_app.setFont(font_before)
        qt_app.setStyleSheet("")
