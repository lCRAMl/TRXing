"""Beschreibung und Benutzung muessen zusammenpassen.

Die Anordnung der Tabs steht als Beschreibung im Quelltext, aus der
qt_controls_pyrs.formbuilder die Bedienelemente baut. Frueher lag sie in
.ui-Dateien, aus denen pyuic6 die ui_*.py erzeugte; was damals das Erzeugen
sicherte, sichert hier der Vergleich zwischen Beschreibung und Benutzung.

Der wichtigste Test ist test_jeder_benutzte_name_wird_gebaut. Beim Umstellen
sind drei Dinge lautlos verlorengegangen, die alle derselben Art sind - ein
Name oder eine Eigenschaft, die in der XML stand und in der Beschreibung
fehlte:

    Pallet2DView          gar nicht importiert, Tab baute nicht mehr auf
    minimumSize 360       Bedienspalte liess sich auf 126 Pixel zusammenziehen
    checked=true          "Muster uebernehmen" startete aus statt an

Der erste fiel beim Starten auf, die beiden anderen erst beim Hinsehen. Diese
Tests fangen die erste Art sofort und die anderen beiden gezielt.

Dass die BAUSTEINE bauen, was sie versprechen, prueft die Bibliothek selbst -
tests/test_formbuilder.py in QtControlsPyRS. Hier geht es nur noch um die
Formulare DIESER Anwendung: dass jeder Name, den ein Tab anspricht, auch
beschrieben ist, und dass die Eigenschaften ankommen, die beim Umstellen
einmal verloren waren.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------
# Beschreibung und Benutzung passen zusammen
# ----------------------------------------------------------------------

def _benutzte_namen(pfad: pathlib.Path) -> set[str]:
    """Alle `self.ui.X`, die ein Modul anspricht."""
    baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    namen = set()
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Attribute):
            continue
        innen = knoten.value
        if (isinstance(innen, ast.Attribute) and innen.attr == "ui"
                and isinstance(innen.value, ast.Name) and innen.value.id == "self"):
            namen.add(knoten.attr)
    return namen


TABS = [
    ("app/palette/tab.py", "app.palette.tab", "PalletTab"),
    ("app/vakuum/tab.py", "app.vakuum.tab", "VacuumTab"),
    ("app/palette/formular.py", "app.palette.formular", "PackageForm"),
]


@pytest.mark.parametrize("pfad, modul, klasse", TABS, ids=[t[2] for t in TABS])
def test_jeder_benutzte_name_wird_gebaut(qtbot, application, pfad, modul, klasse):
    """Was ein Tab unter self.ui anspricht, muss die Beschreibung auch bauen.

    Das ist der Ersatz fuer "die erzeugte Datei ist aktuell": frueher erzeugte
    pyuic6 die Namen, heute kommen sie aus der Beschreibung - und ein
    vergessener Eintrag faellt sonst erst beim Oeffnen des Tabs auf, weit weg
    von der Ursache.
    """
    import importlib

    gebraucht = _benutzte_namen(ROOT / pfad)
    widget = getattr(importlib.import_module(modul), klasse)(application.context)
    qtbot.addWidget(widget)

    fehlend = sorted(name for name in gebraucht if not hasattr(widget.ui, name))
    assert not fehlend, (
        klasse + " spricht Namen an, die die Beschreibung nicht baut: "
        + ", ".join(fehlend)
    )


@pytest.mark.parametrize("pfad, modul, klasse", TABS, ids=[t[2] for t in TABS])
def test_kein_name_wird_zweimal_vergeben(qtbot, application, pfad, modul, klasse):
    """Zwei Bausteine mit demselben Namen: der zweite ueberschreibt den ersten,
    und das faellt nirgends auf."""
    import importlib

    widget = getattr(importlib.import_module(modul), klasse)(application.context)
    qtbot.addWidget(widget)

    namen = widget.ui.namen()
    assert len(namen) == len(set(namen))


# ----------------------------------------------------------------------
# Was beim Umstellen verlorenging - gezielt festgenagelt
# ----------------------------------------------------------------------

def test_die_bedienspalte_behaelt_ihre_mindestbreite(qtbot, application):
    """Sonst laesst sich der Griff des Teilers ueber die Beschriftungen ziehen.

    Stand frueher als minimumSize in der .ui-Datei. Beim Umstellen einmal
    verloren: die Vakuumspalte liess sich auf 126 Pixel zusammenschieben.
    """
    from app.palette.tab import PalletTab
    from app.vakuum.tab import VacuumTab

    for klasse in (PalletTab, VacuumTab):
        tab = klasse(application.context)
        qtbot.addWidget(tab)
        scroll = tab.ui.controls_scroll
        assert scroll.minimumWidth() >= 300, (
            klasse.__name__ + ": die Bedienspalte darf nicht beliebig schmal werden"
        )


def test_das_muster_der_palettierung_wird_vorgegeben_uebernommen(qtbot, application):
    """checked=true stand in der XML und ging beim Umstellen verloren.

    Aufgefallen an einem Test, der ploetzlich dasselbe Ergebnis fuer zwei
    verschiedene Palettiermuster bekam - weil gar keines mehr uebernommen
    wurde.
    """
    from app.vakuum.tab import VacuumTab

    tab = VacuumTab(application.context)
    qtbot.addWidget(tab)
    assert tab.ui.use_pallet_pattern.isChecked()
    assert tab.ui.solve_point.isChecked()


def test_lange_kaestchentexte_brechen_um(qtbot, application):
    """Einzeilig misst "Teilweise aufliegende Sauger..." ueber 600 Bildpunkte
    und zwaenge die ganze Spalte auf diese Breite."""
    from app.vakuum.tab import VacuumTab

    tab = VacuumTab(application.context)
    qtbot.addWidget(tab)
    assert tab.ui.partial_counts.minimumSizeHint().width() < 300
