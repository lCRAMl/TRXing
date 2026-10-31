"""Tests der Rechenwegdokumentation.

Eine Dokumentation, die niemand gegen den Code haelt, veraltet unbemerkt.
Geprueft wird deshalb nicht nur, dass sie sich oeffnen laesst, sondern auch,
dass die Dateien, auf die sie verweist, tatsaechlich existieren und dass jede
Rechnung der Anwendung darin vorkommt.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.gui.help_dialog import full_document, sections

ROOT = pathlib.Path(__file__).resolve().parent.parent


# Inhalt ------------------------------------------------------------------------

def test_every_section_has_content():
    for section in sections():
        assert section.anchor and section.title
        assert len(section.html) > 500, section.title + " ist zu duenn"


def test_anchors_are_unique():
    anchors = [section.anchor for section in sections()]
    assert len(anchors) == len(set(anchors))


def test_document_is_assembled_with_all_anchors():
    document = full_document()
    for section in sections():
        assert 'name="' + section.anchor + '"' in document


@pytest.mark.parametrize(
    "term",
    [
        # Paketdaten
        "Volumen", "Dichte", "Stapellast",
        # Palettierung
        "Rastermass", "Guillotine", "Laeuferverband", "bandweise",
        "Lastkaskade", "Ueberdeckung", "Ausnutzung",
        # Vakuum
        "Dichtlippe", "Wirkungsbereich", "Abreisskraft", "Querkraft",
        "Sicherheitsfaktor", "Reibbeiwert", "Beschleunigung",
        "Blende", "kritische", "Permeabilitaet", "Pumpenkennlinie",
        "Arbeitspunkt", "Bisektion",
        # Aufbau
        "Schichten", "RequestGate", "Reproduzierbarkeit",
    ],
)
def test_every_calculation_is_documented(term):
    """Jede Rechnung, die die Anwendung ausfuehrt, muss erklaert sein."""
    assert term in full_document(), "'" + term + "' fehlt in der Dokumentation"


def test_units_are_documented():
    document = full_document()
    for unit in ("_mm", "_kg", "_n", "_pa", "_m3s"):
        assert unit in document


def test_source_references_point_to_existing_files():
    """Die Verweise auf den Quelltext muessen stimmen.

    Ohne diese Pruefung zeigt die Dokumentation nach der ersten Umbenennung ins
    Leere - und das faellt niemandem auf, weil sie sich trotzdem oeffnen laesst.
    """
    document = full_document()
    referenced = set(re.findall(r"<code>((?:app|tests)/[\w/]+\.py)</code>", document))
    assert referenced, "Es muessen Quelltextverweise vorhanden sein"

    missing = [path for path in sorted(referenced) if not (ROOT / path).is_file()]
    assert not missing, "Verweise auf nicht vorhandene Dateien: " + ", ".join(missing)


def test_the_important_engines_are_referenced():
    """Jede Engine muss in der Dokumentation auftauchen."""
    document = full_document()
    for path in (
        "app/pallet/stacking.py",
        "app/vacuum/physics.py",
        "app/vacuum/physics.py",
        "app/vacuum/physics.py",
        "app/vacuum/calculator.py",
        "app/domain/geometry.py",
    ):
        assert path in document, path + " wird nicht erwaehnt"


def test_datasheet_values_in_the_document_match_the_configuration(settings):
    """Die Tabelle im Kraftkapitel muss zum Saugerkatalog passen."""
    document = full_document()
    for cup_id, force_text in (
        ("spb2_20", "6,8 N"), ("spb2_25", "9,9 N"), ("spb2_30", "14,4 N"),
        ("spb2_40", "24,8 N"), ("spb2_50", "34,6 N"),
    ):
        cup = settings.get_suction_cup(cup_id)
        assert force_text in document
        assert format(cup.theoretical_force_n, "g").replace(".", ",") in force_text


def test_assumptions_are_declared_as_such():
    """Spezifikation 25: die Dokumentation muss Annahmen benennen."""
    document = full_document()
    assert "Modellannahme" in document
    assert "keinen</b>\nSicherheitsfaktor" in document or "keinen" in document
    assert "Naeherung" in document


# Fenster -----------------------------------------------------------------------

def test_dialog_opens_and_lists_every_section(qt_app):
    from app.gui.help_dialog import FormulaHelpDialog

    dialog = FormulaHelpDialog()
    try:
        assert dialog._index.count() == len(sections())
        assert len(dialog._view.toPlainText()) > 10_000
    finally:
        dialog.close()


def test_dialog_search_finds_a_formula(qt_app):
    from app.gui.help_dialog import FormulaHelpDialog

    dialog = FormulaHelpDialog()
    try:
        assert dialog.find_in_document("Bisektion") is True
        assert dialog.find_in_document("Kartoffelsalat") is False
    finally:
        dialog.close()


def test_dialog_jumps_to_a_section(qt_app):
    from app.gui.help_dialog import FormulaHelpDialog

    dialog = FormulaHelpDialog()
    try:
        dialog.show_section("vacuum_flow")
        assert dialog._index.currentItem().text().startswith("6.")
    finally:
        dialog.close()


def test_help_is_reachable_from_the_menu(qt_app, tmp_path):
    """Der vom Benutzer geforderte Weg: Menue Hilfe."""
    from pathlib import Path

    from app.application import Application
    from app.application import MainWindow

    application = Application(
        config_directory=Path(__file__).resolve().parent.parent / "config",
        log_directory=tmp_path / "logs",
    )
    application.startup()
    window = MainWindow(application.context, application.registry)
    try:
        titles = []
        for menu_action in window.menuBar().actions():
            if menu_action.menu() is not None:
                titles.extend(a.text() for a in menu_action.menu().actions())
        assert "Rechenwege und Formeln" in titles

        window.show_formulas()
        qt_app.processEvents()
        assert window._formula_help is not None

        # Zweimal oeffnen darf kein zweites Fenster erzeugen.
        first = window._formula_help
        window.show_formulas()
        assert window._formula_help is first
        first.close()
    finally:
        window.close()
        application.shutdown()


# ----------------------------------------------------------------------
# Die Kapitel liegen als Dateien daneben
# ----------------------------------------------------------------------

def test_every_chapter_file_is_well_formed():
    """Titelzeile und Dateiname sind der ganze Vertrag einer Kapiteldatei.

    Geprueft an den Dateien und nicht am Ergebnis: ein Kapitel ohne
    Titelzeile wuerde sonst erst beim Oeffnen der Hilfe auffallen, und die
    Meldung stuende dann weit von der Ursache.
    """
    from app.gui.help_dialog import help_texts_dir

    dateien = sorted(help_texts_dir().glob("*.html"))
    assert len(dateien) >= 7, "Es fehlen Kapiteldateien: " + str(dateien)

    for datei in dateien:
        erste = datei.read_text(encoding="utf-8").split("\n", 1)[0]
        assert erste.startswith("titel:"), datei.name + ": " + repr(erste[:40])
        assert erste[len("titel:"):].strip(), datei.name + ": Titel ist leer"
        nummer, strich, marke = datei.stem.partition("-")
        assert strich and nummer.isdigit() and marke, (
            datei.name + ": erwartet wird die Form 01-marke.html"
        )


def test_the_chapter_order_comes_from_the_file_names():
    """01- bis 07-: die Reihenfolge steht an einer Stelle, nicht an zwei."""
    from app.gui.help_dialog import help_texts_dir, sections

    aus_dateien = [d.stem.partition("-")[2]
                   for d in sorted(help_texts_dir().glob("*.html"))]
    assert [s.anchor for s in sections()] == aus_dateien


def test_formulas_stay_escaped():
    """Die Maskierung ist kein Schmuck, sondern hat einen Fehler behoben.

    Ein Vergleich wie "pi <= pi_krit" zerlegt ohne Maskierung das ganze
    Dokument: die Anzeige liest das Kleinerzeichen als Beginn eines
    HTML-Elements und verschluckt alles bis zum naechsten groesser-als - samt
    Formel und der Formatierung dahinter. Beim Umzug der Texte in Dateien
    haette man das leicht verlieren koennen, indem man die Formeln als
    fertiges HTML hinschreibt.
    """
    from app.gui.help_dialog import full_document, help_texts_dir

    roh = "\n".join(d.read_text(encoding="utf-8")
                    for d in help_texts_dir().glob("*.html"))
    assert "<=" in roh, "In den Quelldateien steht kein unmaskierter Vergleich"

    dokument = full_document()
    assert "&lt;=" in dokument, "Die Vergleiche sind nicht maskiert"
    # In einem <pre>-Block darf kein rohes Kleinerzeichen mehr stehen.
    for block in dokument.split("<pre>")[1:]:
        formel = block.split("</pre>")[0]
        assert "<" not in formel, "Unmaskiertes < in einer Formel: " + formel[:60]


def test_a_chapter_without_a_title_line_says_so():
    """Eine klare Meldung statt eines Kapitels mit HTML als Ueberschrift."""
    import pathlib as _pathlib

    from app.gui.help_dialog import _lies_kapitel

    import tempfile
    with tempfile.TemporaryDirectory() as ordner:
        datei = _pathlib.Path(ordner) / "01-probe.html"
        datei.write_text("<h1>Ohne Titelzeile</h1>\n", encoding="utf-8")
        with pytest.raises(ValueError, match="titel:"):
            _lies_kapitel(datei)


def test_the_help_texts_travel_with_the_package():
    """Das Bauskript nimmt den Ordner mit.

    Bleibt der --add-data-Eintrag weg, startet die gepackte Fassung ohne
    Hilfe - und zwar erst beim Klick auf das Menue, lange nach der
    Auslieferung.
    """
    import AUTOBUILD

    from app.gui.help_dialog import HELP_TEXTS_DIRNAME

    ziele = [ziel for _quelle, ziel in AUTOBUILD.DATA_FILES]
    assert any(z.endswith(HELP_TEXTS_DIRNAME) for z in ziele), (
        "AUTOBUILD.DATA_FILES nimmt " + HELP_TEXTS_DIRNAME
        + " nicht mit: " + str(ziele)
    )
