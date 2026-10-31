"""Beschreibung und Benutzung muessen zusammenpassen.

Die Anordnung der Tabs steht als Beschreibung im Quelltext, aus der
app.gui.form_builder die Bedienelemente baut. Frueher lag sie in
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

Zwei Sorten Test stehen hier. Zuerst, dass die BAUSTEINE bauen, was sie
versprechen - das ist die Mechanik von app/gui/form_builder.py. Danach,
dass die Formulare DIESER Anwendung zu dem passen, was die Tabs ansprechen.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from PyQt6.QtWidgets import QCheckBox, QLabel, QPushButton, QWidget

from qt_controls_pyrs import (
    CompactDropdown, CompactIntField, CompactNumberField, CompactResultGrid
)
from app.gui.form_builder import (
    Auswahlknopf, Ganzzahl, Gruppe, Hinweis, Knopf, Platz, Raster, Schalter,
    Text, Wahl, Zahl, Zeile, baue
)

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------
# Die Bausteine bauen, was sie versprechen
# ----------------------------------------------------------------------

def test_jeder_baustein_wird_zu_seinem_bedienelement(qtbot):
    beschreibung = [
        Gruppe("Probe", [
            [Zahl("zahl", "Zahl", "mm", dict(min=1.0, max=9.0, stellen=2, wert=3.0))],
            [Ganzzahl("stueck", "Stueck", "Stueck", dict(min=0, max=50, wert=7))],
            [Wahl("auswahl", "Auswahl")],
            [Text("text", "Text", platzhalter="hier")],
            [Schalter("schalter", "Schalter")],
            [Hinweis("ein Hinweis", name="hinweis")],
        ]),
        Zeile([Knopf("knopf", "Knopf")]),
        Raster("raster", "Ergebnis"),
        Platz("platz"),
    ]
    widget, ui = baue(beschreibung)
    qtbot.addWidget(widget)

    assert isinstance(ui.zahl, CompactNumberField)
    assert ui.zahl.value() == pytest.approx(3.0)
    assert ui.zahl.unit() == "mm"
    assert ui.zahl.spin.decimals() == 2

    assert isinstance(ui.stueck, CompactIntField)
    assert ui.stueck.value() == 7

    assert isinstance(ui.auswahl, CompactDropdown)
    assert ui.text.placeholderText() == "hier"
    assert isinstance(ui.schalter, QCheckBox)
    assert isinstance(ui.hinweis, QLabel)
    assert isinstance(ui.knopf, QPushButton)
    assert isinstance(ui.raster, CompactResultGrid)
    assert isinstance(ui.platz, QWidget)


def test_vorgaben_gehen_nicht_verloren(qtbot):
    """Angehakt, gesperrt, unsichtbar, Erklaerungstext - alles stand in der XML."""
    widget, ui = baue([
        Gruppe("Probe", [
            [Schalter("an", "An", angehakt=True, hinweis="erklaert")],
            [Schalter("aus", "Aus")],
            [Auswahlknopf("gewaehlt", "Gewaehlt", angehakt=True)],
        ]),
        Zeile([
            Knopf("vorgabe", "Berechnen", vorgabe=True),
            Knopf("gesperrt", "Abbrechen", aktiv=False),
            Knopf("versteckt", "Kamera", sichtbar=False),
        ]),
    ])
    qtbot.addWidget(widget)

    assert ui.an.isChecked() and ui.an.toolTip() == "erklaert"
    assert not ui.aus.isChecked()
    assert ui.gewaehlt.isChecked()
    assert ui.vorgabe.isDefault()
    assert not ui.gesperrt.isEnabled()
    assert not ui.versteckt.isVisible()


def test_lange_eintraege_ziehen_die_spalte_nicht_auseinander(qtbot):
    """Die Breitenbremse der Auswahlfelder, frueher als sizeAdjustPolicy in der XML."""
    widget, ui = baue([Gruppe("Probe", [[Wahl("auswahl", "Auswahl", zeichen=12)]])])
    qtbot.addWidget(widget)

    ui.auswahl.addItems(["kurz", "Rueckschlagventil (schliesst bei offenem Sauger)"])
    assert ui.auswahl.minimumContentsLength() == 12


def test_ein_unbekannter_name_sagt_welche_es_gibt(qtbot):
    widget, ui = baue([Gruppe("Probe", [[Zahl("laenge", "Laenge", "mm")]])])
    qtbot.addWidget(widget)

    with pytest.raises(AttributeError, match="laenge"):
        _ = ui.gibtesnicht


def test_ein_unbekannter_baustein_sagt_was_er_ist(qtbot):
    """Ein neuer Zeilentyp braucht einen Zweig in _zelle() - und zwar laut."""
    with pytest.raises(TypeError, match="object"):
        baue([Gruppe("Probe", [[object()]])])


def test_beschriftung_oben_statt_daneben(qtbot):
    """`oben=True` legt zwei Rasterzeilen je Formularzeile an.

    Nebeneinander addieren sich Beschriftung und Feld; stehen zwei Paare in
    einer Zeile, addieren sich vier Breiten. Uebereinander zaehlt je Spalte das
    groessere von beiden.
    """
    daneben, _ = baue([Gruppe("Probe", [
        [Zahl("a", "Eine lange Beschriftung", "mm"),
         Zahl("b", "Noch eine lange", "mm")],
    ])])
    oben, _ = baue([Gruppe("Probe", [
        [Zahl("a", "Eine lange Beschriftung", "mm"),
         Zahl("b", "Noch eine lange", "mm")],
    ], oben=True)])
    qtbot.addWidget(daneben)
    qtbot.addWidget(oben)

    assert oben.sizeHint().width() < daneben.sizeHint().width()
    assert oben.sizeHint().height() > daneben.sizeHint().height()


def test_eine_zeile_ohne_rahmen_dehnt_auf_wunsch(qtbot):
    """Ohne `dehnen` schwimmen zwei Knoepfe in voller Breite auseinander."""
    eng, _ = baue([Zeile([Knopf("a", "Eins"), Knopf("b", "Zwei")], dehnen=True)])
    qtbot.addWidget(eng)
    eng.resize(600, 60)
    eng.show()
    qtbot.waitExposed(eng)

    knoepfe = eng.findChildren(QPushButton)
    assert len(knoepfe) == 2
    # Mit Dehnraum rechts bleiben beide links beieinander.
    assert knoepfe[1].geometry().right() < 400


def test_ein_hinweis_hat_eine_mindestbreite(qtbot):
    """Ohne sie bricht ein langer Hinweis in eine Saeule von zwei Woertern um."""
    from qt_controls_pyrs import COMPACT_WRAP_WIDTH

    widget, ui = baue([Gruppe("Probe", [
        [Hinweis("Ein ziemlich langer Erklaerungstext, der umbrechen soll, "
                 "aber nicht zu einer Saeule werden darf.", name="h")],
    ])])
    qtbot.addWidget(widget)

    assert ui.h.wordWrap()
    assert ui.h.minimumWidth() == COMPACT_WRAP_WIDTH
    assert ui.h.property("role") == "note"


# ----------------------------------------------------------------------
# Die Abstaende
# ----------------------------------------------------------------------

def test_die_abstaende_kommen_aus_den_konstanten(qtbot):
    """Wo man die Dichte eines Formulars einstellt - an genau drei Zahlen."""
    from qt_controls_pyrs import (
        COMPACT_GROUP_SPACING, COMPACT_SPACING, COMPACT_SPACING_X
    )

    widget, _ui = baue([
        Gruppe("Eins", [[Zahl("a", "A", "mm")]]),
        Gruppe("Zwei", [[Zahl("b", "B", "mm")]]),
    ])
    qtbot.addWidget(widget)

    aussen = widget.layout()
    assert aussen.spacing() == COMPACT_GROUP_SPACING

    raster = aussen.itemAt(0).widget().layout()
    assert raster.verticalSpacing() == COMPACT_SPACING
    assert raster.horizontalSpacing() == COMPACT_SPACING_X


def test_eine_andere_zahl_wirkt_auch(qtbot, monkeypatch):
    """Der eigentliche Test.

    Dass die Zahlen uebereinstimmen, koennte Zufall sein - beide sind 4. Hier
    wird eine andere gesetzt, und das Formular muss sie uebernehmen. Genau das
    ging vorher NICHT: COMPACT_SPACING stand im Modul, war exportiert und
    dokumentiert, und die Abstaende waren daneben als 8, 4 und 6 fest
    verdrahtet. Wer an der Konstanten drehte, sah nichts geschehen.
    """
    from app.gui import form_builder

    monkeypatch.setattr(form_builder, "COMPACT_SPACING", 17)
    monkeypatch.setattr(form_builder, "COMPACT_SPACING_X", 23)
    monkeypatch.setattr(form_builder, "COMPACT_GROUP_SPACING", 29)

    widget, _ui = baue([Gruppe("Probe", [[Zahl("a", "A", "mm")]])])
    qtbot.addWidget(widget)

    assert widget.layout().spacing() == 29
    raster = widget.layout().itemAt(0).widget().layout()
    assert raster.verticalSpacing() == 17
    assert raster.horizontalSpacing() == 23


def test_zwischen_gruppen_steht_mehr_luft_als_zwischen_zeilen(qtbot):
    """Sonst sieht ein Formular aus wie eine einzige lange Liste."""
    from qt_controls_pyrs import COMPACT_GROUP_SPACING, COMPACT_SPACING

    assert COMPACT_GROUP_SPACING > COMPACT_SPACING


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
    ("app/gui/pallet/tab.py", "app.gui.pallet.tab", "PalletTab"),
    ("app/gui/vacuum/tab.py", "app.gui.vacuum.tab", "VacuumTab"),
    ("app/gui/pallet/form.py", "app.gui.pallet.form", "PackageForm"),
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
    from app.gui.pallet.tab import PalletTab
    from app.gui.vacuum.tab import VacuumTab

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
    from app.gui.vacuum.tab import VacuumTab

    tab = VacuumTab(application.context)
    qtbot.addWidget(tab)
    assert tab.ui.use_pallet_pattern.isChecked()
    assert tab.ui.solve_point.isChecked()


def test_lange_kaestchentexte_brechen_um(qtbot, application):
    """Einzeilig misst "Teilweise aufliegende Sauger..." ueber 600 Bildpunkte
    und zwaenge die ganze Spalte auf diese Breite."""
    from app.gui.vacuum.tab import VacuumTab

    tab = VacuumTab(application.context)
    qtbot.addWidget(tab)
    assert tab.ui.partial_counts.minimumSizeHint().width() < 300
