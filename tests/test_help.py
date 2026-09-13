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

from app.gui.help.content import full_document, sections

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
        "app/engines/palletizing/loads.py",
        "app/engines/vacuum/force.py",
        "app/engines/vacuum/flow.py",
        "app/engines/vacuum/leakage.py",
        "app/engines/vacuum/calculator.py",
        "app/engines/geometry/shapes.py",
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
    from app.gui.help.formula_dialog import FormulaHelpDialog

    dialog = FormulaHelpDialog()
    try:
        assert dialog._index.count() == len(sections())
        assert len(dialog._view.toPlainText()) > 10_000
    finally:
        dialog.close()


def test_dialog_search_finds_a_formula(qt_app):
    from app.gui.help.formula_dialog import FormulaHelpDialog

    dialog = FormulaHelpDialog()
    try:
        assert dialog.find_in_document("Bisektion") is True
        assert dialog.find_in_document("Kartoffelsalat") is False
    finally:
        dialog.close()


def test_dialog_jumps_to_a_section(qt_app):
    from app.gui.help.formula_dialog import FormulaHelpDialog

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
    from app.gui.main_window import MainWindow

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
