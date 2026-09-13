"""Tests der Oberflaeche und des Zusammenspiels der Tabs.

Der Schwerpunkt liegt auf dem, was Spezifikation 10 und 11 verlangen: die
Anwendung startet, alle Module erscheinen, eine Aenderung der Paketdaten
erreicht jede abhaengige Anzeige, und die Oberflaeche friert waehrend einer
Berechnung nicht ein.

Die Paketdaten sind kein Modul und kein Tab: ihr Formular sitzt am Kopf der
Palettierung. Die Tests holen es sich ueber den Tab, der es haelt - dafuer gibt
es die Vorrichtung package_form.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from app.services.app_state import StateChange

pytestmark = pytest.mark.usefixtures("qt_app")

#: Stellen der Tabs in der Leiste. Seit die Paketdaten im Kopf der Palettierung
#: sitzen, sind es zwei - und der Umzug soll an einer Stelle nachzuziehen sein.
TAB_PALLET = 0
TAB_VACUUM = 1


@pytest.fixture
def application(tmp_path):
    """Vollstaendig gestartete Anwendung auf der mitgelieferten Konfiguration."""
    from pathlib import Path

    from app.application import Application

    root = Path(__file__).resolve().parent.parent
    app = Application(config_directory=root / "config", log_directory=tmp_path / "logs")
    result = app.startup()
    assert result.ok
    yield app
    app.shutdown()


@pytest.fixture
def package_form(window):
    """Das Paketformular im Kopf der Palettierung."""
    return window._tab_manager.widget_for("pallet")._package


@pytest.fixture
def window(qt_app, application):
    from app.gui.main_window import MainWindow

    win = MainWindow(application.context, application.registry)
    # Der zuletzt benutzte Tab wird aus den Benutzereinstellungen
    # wiederhergestellt. Fuer einen Test waere das eine Abhaengigkeit von der
    # Vorgeschichte des Rechners - deshalb hier ausdruecklich auf den ersten.
    win.centralWidget().setCurrentIndex(TAB_PALLET)
    win.show()
    qt_app.processEvents()
    yield win
    win.close()


def _settle(qt_app, application, timeout_s: float = 10.0) -> None:
    """Wartet, bis keine Berechnung mehr laeuft, und stellt die Signale zu."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        qt_app.processEvents()
        if application.jobs.active_count == 0:
            break
        time.sleep(0.005)
    qt_app.processEvents()


# Start ------------------------------------------------------------------------

def test_application_starts(application):
    assert application.context is not None
    assert application.registry is not None
    assert len(application.registry) == 2


def test_status_report_is_complete(application):
    report = application.status_report()
    assert report["config_ok"] is True
    assert report["pallets"] >= 4
    assert report["suction_cups"] >= 24
    assert report["modules"] == ["pallet", "vacuum"]


def test_both_tabs_appear(window):
    tabs = window.centralWidget()
    assert tabs.count() == 2
    assert [tabs.tabText(i) for i in range(2)] == ["Palettierung", "Vakuumplatte"]


def test_no_tab_failed_to_build(window, application):
    """Ein gescheiterter Tab bekommt einen Platzhalter - der darf hier nicht auftauchen."""
    from app.gui.pallet.pallet_tab import PalletTab
    from app.gui.vacuum.vacuum_tab import VacuumTab

    manager = window._tab_manager
    assert isinstance(manager.widget_for("pallet"), PalletTab)
    assert isinstance(manager.widget_for("vacuum"), VacuumTab)


def test_the_package_form_sits_at_the_top_of_the_pallet_tab(window, package_form):
    """Die Paketdaten sind kein eigener Tab mehr, sondern das erste Formular
    der Palettierung - noch ueber der Palettenauswahl."""
    from app.gui.package.package_form import PackageForm

    tab = window._tab_manager.widget_for("pallet")
    assert isinstance(package_form, PackageForm)
    assert package_form.parent() is tab.ui.package_host

    root = tab.ui.root
    assert root.indexOf(tab.ui.package_host) == 0
    assert root.indexOf(tab.ui.package_host) < root.indexOf(tab.ui.splitter)
    assert tab.ui.selection_box.title() == "Palettenauswahl"


def test_configuration_appears_in_the_dropdowns(window, application):
    """Spezifikation 43: Config-Daten erscheinen in den Auswahlfeldern."""
    pallet_tab = window._tab_manager.widget_for("pallet")
    vacuum_tab = window._tab_manager.widget_for("vacuum")

    assert pallet_tab.ui.pallet_box.count() == len(application.settings.get_pallets())
    assert pallet_tab.ui.pattern_box.count() == len(application.settings.get_patterns())
    assert vacuum_tab.ui.cup_box.count() == len(application.settings.get_suction_cups())


def test_a_new_module_needs_only_one_line(application):
    """Spezifikation 06: ein weiteres Modul aendert nichts an der Architektur."""
    from PyQt6.QtWidgets import QLabel

    from app.gui.module_registry import ModuleRegistry

    class DemoModule:
        module_id = "demo"
        title = "Demomodul"
        order = 99

        def create_widget(self, context):
            return QLabel("Demo")

    registry = ModuleRegistry()
    registry.register_all([DemoModule()])
    assert registry.ids() == ("demo",)
    assert registry.get("demo").create_widget(application.context) is not None


# Paketdaten -------------------------------------------------------------------

def test_package_defaults_reach_the_state_immediately(window, application):
    """Beim Start muss das angezeigte Paket auch im Zustand stehen.

    Sonst melden die Tabs 'keine Paketdaten', obwohl im Formular darueber
    gueltige Zahlen stehen.
    """
    package = application.state.snapshot().package
    assert package is not None
    assert package.length_mm > 0 and package.weight_kg > 0


def test_valid_input_updates_the_state(package_form, application, qt_app):
    package_form.ui.length.spin.setValue(650.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    assert application.state.snapshot().package.length_mm == 650.0


def test_invalid_input_is_shown_at_the_field(package_form, application, qt_app):
    """Spezifikation 34: Fehler direkt am Eingabefeld, nicht im Dialog."""
    before = application.state.snapshot().package

    package_form.ui.weight.spin.setValue(0.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    assert package_form.ui.weight._message.text(), "Am Gewichtsfeld muss eine Meldung stehen"
    assert application.state.snapshot().package == before, "Ungueltiges Paket darf nicht in den Zustand"


def test_derived_values_are_shown(package_form, qt_app):
    package_form.ui.length.spin.setValue(400.0)
    package_form.ui.width.spin.setValue(300.0)
    package_form.ui.height.spin.setValue(200.0)
    qt_app.processEvents()

    assert package_form.ui.derived._rows["volume"].text() == "24.00 l"
    assert package_form.ui.derived._rows["footprint"].text().startswith("1200")


def test_same_value_does_not_bump_the_revision(package_form, application, qt_app):
    """Eine Neueingabe desselben Werts darf kein gueltiges Ergebnis entwerten."""
    package_form._debouncer.flush()
    before = application.state.revision

    package_form._commit()
    qt_app.processEvents()
    assert application.state.revision == before


# Palettierung -----------------------------------------------------------------

def test_pallet_tab_calculates(window, application, qt_app):
    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    _settle(qt_app, application)

    assert tab._result is not None
    assert tab._result.total_count > 0
    assert tab.ui.results._rows["total"].text() == str(tab._result.total_count)


def test_pallet_view_switches_to_3d(window, application, qt_app):
    """Spezifikation 43: die 2D/3D-Umschaltung funktioniert.

    Ob VTK verfuegbar ist, entscheidet der Adapter; ohne die Bibliothek
    erscheint die Ersatzansicht. Beides ist ein gueltiger Ausgang - der Tab
    darf in keinem Fall scheitern.
    """
    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    _settle(qt_app, application)

    tab.ui.button_3d.setChecked(True)
    qt_app.processEvents()

    assert tab.ui.views.currentIndex() == 1
    assert tab._scene is not None
    assert tab._scene.widget() is not None

    tab.ui.button_2d.setChecked(True)
    qt_app.processEvents()
    assert tab.ui.views.currentIndex() == 0


def test_layer_selection_follows_the_result(window, application, qt_app):
    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    _settle(qt_app, application)

    assert tab.ui.layer_box.count() == tab._result.layer_count
    tab.ui.layer_box.setCurrentIndex(1)
    qt_app.processEvents()
    assert tab.ui.view_2d._layer_index == 1


def test_impossible_pallet_input_shows_a_message(window, package_form, application, qt_app):
    package_form.ui.length.spin.setValue(2000.0)
    package_form.ui.width.spin.setValue(2000.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    _settle(qt_app, application)

    assert tab.ui.banner._label.text(), "Der Fehlschlag muss im Hinweisband stehen"
    assert "passt in keiner" in tab.ui.banner._label.text()


# Vakuum -----------------------------------------------------------------------

def test_vacuum_tab_calculates(window, application, qt_app):
    tab = window._tab_manager.widget_for("vacuum")
    tab.calculate()
    _settle(qt_app, application)

    assert tab._result is not None
    assert tab.ui.results._rows["status"].text() in ("Sicher", "Grenzwertig", "Nicht ausreichend")
    assert tab.ui.results._rows["cups_total"].text()


def test_vacuum_shows_the_datasheet_values_of_the_cup(window, application, qt_app):
    """Die Datenblattangaben stehen am Saugerfeld.

    Der frueher danebenstehende Kasten "Annahmen und Herkunft der Werte" ist
    entfallen; die Annahmen des Rechenmodells fuehrt weiterhin der Rechenweg,
    nachzulesen unter Hilfe - Rechenwege und Formeln.
    """
    tab = window._tab_manager.widget_for("vacuum")
    tab.calculate()
    _settle(qt_app, application)

    info = tab.ui.cup_info.text()
    assert "Datenblatt" in info
    assert "Dichtlippe" in info
    assert "Abreisskraft" in info


def test_vacuum_result_is_split_over_two_columns(window, application, qt_app):
    tab = window._tab_manager.widget_for("vacuum")
    tab.calculate()
    _settle(qt_app, application)

    assert tab.ui.results._rows["status"].text() in ("Sicher", "Grenzwertig", "Nicht ausreichend")
    assert "mbar" in tab.ui.flow_results._rows["vacuum"].text()
    assert "m3/h" in tab.ui.flow_results._rows["flow_required"].text()


def test_model_assumptions_are_still_recorded(window, application, qt_app):
    """Spezifikation 25 bleibt erfuellt: die Annahmen stehen im Rechenweg.

    Nur die staendige Anzeige daneben ist entfallen - sie kostete die halbe
    Breite fuer einen Text, der sich nie aendert.
    """
    tab = window._tab_manager.widget_for("vacuum")
    tab.calculate()
    _settle(qt_app, application)

    sources = {entry.source for entry in tab._result.trace.assumptions}
    assert "datasheet" in sources
    assert "model" in sources


def test_vacuum_cup_limit_follows_the_plate(window, qt_app):
    tab = window._tab_manager.widget_for("vacuum")
    tab.ui.plate_length.spin.setValue(400.0)
    tab.ui.plate_width.spin.setValue(300.0)
    qt_app.processEvents()
    small = tab.ui.cup_count.spin.maximum()

    tab.ui.plate_length.spin.setValue(1200.0)
    tab.ui.plate_width.spin.setValue(900.0)
    qt_app.processEvents()
    large = tab.ui.cup_count.spin.maximum()

    assert large > small


# Zusammenspiel ----------------------------------------------------------------

def test_package_change_marks_the_other_tabs_for_recalculation(
    window, package_form, application, qt_app
):
    """Eine Aenderung der Paketdaten merkt jede abhaengige Anzeige zum
    Nachrechnen vor.

    Gerechnet wird nicht sofort: die Vakuumplatte ist verdeckt, waehrend der
    Benutzer oben tippt. Rechenzeit fuer Ergebnisse, die niemand ansieht, waere
    verschenkt.
    """
    tabs = window.centralWidget()
    tabs.setCurrentIndex(TAB_PALLET)
    pallet = window._tab_manager.widget_for("pallet")
    vacuum = window._tab_manager.widget_for("vacuum")
    pallet.calculate()
    vacuum.calculate()
    _settle(qt_app, application)

    assert pallet._needs_recalculation is False
    assert vacuum._needs_recalculation is False

    package_form.ui.width.spin.setValue(350.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    assert pallet._needs_recalculation is True
    assert vacuum._needs_recalculation is True
    assert pallet.ui.banner._label.text() == "", "Kein Hinweisband - es wird nachgerechnet"
    assert vacuum.ui.banner._label.text() == ""


def test_switching_to_a_tab_recalculates_with_the_new_values(
    window, package_form, application, qt_app
):
    """Der vom Benutzer genannte Ablauf: Werte aendern, Tab anklicken, dort
    steht das Ergebnis zu den neuen Werten.

    Seit die Paketdaten im Kopf der Palettierung stehen, fuehrt der Weg ueber
    die Vakuumplatte und zurueck - und muss dasselbe leisten.
    """
    tabs = window.centralWidget()
    tabs.setCurrentIndex(TAB_PALLET)
    pallet = window._tab_manager.widget_for("pallet")

    package_form.ui.length.spin.setValue(400.0)
    package_form.ui.width.spin.setValue(300.0)
    package_form.ui.height.spin.setValue(200.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    pallet.calculate()
    _settle(qt_app, application)
    first = pallet._result.total_count
    assert pallet._result.package.width_mm == 300.0

    tabs.setCurrentIndex(TAB_VACUUM)
    package_form.ui.width.spin.setValue(600.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    tabs.setCurrentIndex(TAB_PALLET)
    _settle(qt_app, application)

    assert pallet._result.package.width_mm == 600.0, "Das Ergebnis muss zum neuen Paket gehoeren"
    assert pallet._result.total_count != first
    assert pallet._needs_recalculation is False


def test_a_visible_tab_recalculates_without_being_switched(window, application, qt_app):
    """Steht der Tab bereits im Vordergrund, wird sofort nachgerechnet."""
    tabs = window.centralWidget()
    tabs.setCurrentIndex(TAB_VACUUM)
    vacuum = window._tab_manager.widget_for("vacuum")
    vacuum.calculate()
    _settle(qt_app, application)
    before = vacuum._result.meta.request_id

    application.packages.update_package(
        replace(application.state.snapshot().package, weight_kg=12.0)
    )
    vacuum._debouncer.flush()
    _settle(qt_app, application)

    assert vacuum._result.meta.request_id > before
    assert vacuum._result.actual_mass_kg > 0


def test_new_package_changes_the_result(window, package_form, application, qt_app):
    """M10: Paket 400x300x200 rechnen, Breite aendern, neu rechnen."""
    pallet = window._tab_manager.widget_for("pallet")

    package_form.ui.length.spin.setValue(400.0)
    package_form.ui.width.spin.setValue(300.0)
    package_form.ui.height.spin.setValue(200.0)
    package_form._debouncer.flush()
    pallet.calculate()
    _settle(qt_app, application)
    first = pallet._result.total_count

    package_form.ui.width.spin.setValue(600.0)
    package_form._debouncer.flush()
    pallet.calculate()
    _settle(qt_app, application)

    assert pallet._result.total_count != first


def test_pattern_from_the_pallet_tab_reaches_the_vacuum_tab(window, application, qt_app):
    """Spezifikation 18: das Muster der Palettierung ordnet die Pakete der
    Vakuumplatte an."""
    pallet = window._tab_manager.widget_for("pallet")
    vacuum = window._tab_manager.widget_for("vacuum")
    vacuum.ui.package_count.spin.setValue(4)

    grid_index = pallet.ui.pattern_box.findData("aligned")
    pallet.ui.pattern_box.setCurrentIndex(grid_index)
    qt_app.processEvents()
    vacuum.calculate()
    _settle(qt_app, application)
    grid_rects = vacuum._result.package_rects

    brick_index = pallet.ui.pattern_box.findData("brick")
    pallet.ui.pattern_box.setCurrentIndex(brick_index)
    qt_app.processEvents()
    vacuum.calculate()
    _settle(qt_app, application)

    assert application.state.snapshot().pattern_id == "brick"
    assert vacuum._result.package_rects != grid_rects


def test_invalidation_map_covers_every_change(application):
    """Jede Zustandsaenderung muss wissen, welche Anzeige sie entwertet."""
    from app.services.app_state import AppState

    for change in StateChange:
        assert AppState.invalidated_channels(change), (
            change.name + " entwertet keinen Kanal - vermutlich beim Ergaenzen vergessen"
        )


# Nebenlaeufigkeit --------------------------------------------------------------

def test_calculation_does_not_block_the_gui(window, package_form, application, qt_app):
    """Spezifikation 07: der Oberflaechen-Thread rechnet nicht.

    Geprueft wird, dass der Aufruf sofort zurueckkehrt und die Berechnung
    danach noch laeuft - der Beweis, dass niemand auf ein Ergebnis wartet.
    """
    package_form.ui.length.spin.setValue(120.0)
    package_form.ui.width.spin.setValue(95.0)
    package_form.ui.height.spin.setValue(70.0)
    package_form._debouncer.flush()
    qt_app.processEvents()

    tab = window._tab_manager.widget_for("pallet")
    started = time.perf_counter()
    tab.calculate()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25, "calculate() darf nicht auf das Ergebnis warten"
    _settle(qt_app, application, timeout_s=30.0)
    assert tab._result is not None


def test_rapid_changes_produce_one_result(window, application, qt_app):
    """Spezifikation 32: Entprellung statt eines Jobs je Tastendruck."""
    tab = window._tab_manager.widget_for("pallet")
    before = application.jobs.counters()["fertig"]

    for height in (600.0, 800.0, 1000.0, 1200.0, 1400.0):
        tab.ui.max_height.spin.setValue(height)
    assert tab._debouncer.pending, "Die Aenderungen muessen gesammelt werden"

    tab._debouncer.flush()
    _settle(qt_app, application)

    assert application.jobs.counters()["fertig"] - before <= 1


def test_the_last_request_wins(window, application, qt_app):
    """Spezifikation 08: das ueberholte Ergebnis erreicht die Anzeige nicht."""
    tab = window._tab_manager.widget_for("pallet")

    tab.ui.max_height.set_value(1600.0)
    tab.calculate()
    tab.ui.max_height.set_value(600.0)
    tab.calculate()
    _settle(qt_app, application)

    assert tab._result is not None
    assert tab._result.layer_count == 3  # 600 mm / 200 mm
    assert tab._result.meta.request_id == application.gate.latest("pallet")


# Statusleiste und Probleme ----------------------------------------------------

def test_warnings_reach_the_problem_list(window, application, qt_app):
    tab = window._tab_manager.widget_for("vacuum")
    tab.calculate()
    _settle(qt_app, application)

    entries = application.reporter.problems.entries()
    assert entries, "Die Vakuumrechnung meldet Warnungen zu offenen Saugern"
    assert window._status._problems.text() != "Keine Probleme"


def test_problem_panel_opens(window, qt_app):
    window.show_problems()
    qt_app.processEvents()
    assert window._problem_panel is not None
    assert window._problem_panel.isVisible()
    window._problem_panel.close()


def test_no_modal_dialog_for_a_calculation_error(
    window, package_form, application, qt_app, monkeypatch
):
    """Spezifikation 09: normale Rechenfehler erscheinen nicht als Dialog."""
    from PyQt6.QtWidgets import QMessageBox

    shown: list[str] = []
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: shown.append(name))

    package_form.ui.length.spin.setValue(3000.0)
    package_form.ui.width.spin.setValue(3000.0)
    package_form._debouncer.flush()

    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    _settle(qt_app, application)

    assert shown == [], "Ein Rechenfehler darf keinen Dialog oeffnen"


def test_configuration_reload_from_the_menu(window, application, qt_app):
    before = len(application.settings.get_pallets())
    window._reload_config()
    qt_app.processEvents()
    assert len(application.settings.get_pallets()) == before


def test_shutdown_stops_everything(window, application, qt_app):
    tab = window._tab_manager.widget_for("pallet")
    tab.calculate()
    window.close()
    qt_app.processEvents()
    assert application.jobs.active_count == 0


# Programmsymbol ----------------------------------------------------------------

def test_the_application_icon_is_there(qt_app):
    """Das Symbol laedt und bringt mehrere Aufloesungen mit.

    Eine .ico traegt 16 bis 512 Bildpunkte in einer Datei; Windows greift sich
    die passende. Bleibt nur eine uebrig, sieht sie in der anderen Groesse
    ausgefranst aus.
    """
    from app.gui.icons import app_icon, app_icon_path

    assert app_icon_path().is_file(), "pallet.ico fehlt neben app/gui/icons/__init__.py"

    icon = app_icon()
    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    assert {16, 32, 256} <= sizes, "kleine und grosse Aufloesung muessen beide drin sein"


def test_the_icon_travels_with_the_package():
    """Das Bauskript nimmt das Symbol mit - zweimal.

    Als Symbol der .exe (--icon) und als Datei im Paket, weil die Anwendung es
    zur Laufzeit als Fenstersymbol setzt. Faellt eines von beiden weg, merkt es
    niemand vor der Auslieferung.
    """
    import AUTOBUILD

    from app.gui.icons import app_icon_path

    assert AUTOBUILD.ICON_FILE == app_icon_path(), (
        "Bauskript und Anwendung meinen verschiedene Dateien"
    )
    assert AUTOBUILD.ICON_FILE.is_file()

    bundled = {target for _source, target in AUTOBUILD.DATA_FILES}
    assert "app/gui/icons" in bundled, "Der Symbolordner fehlt in DATA_FILES"


def test_the_spacing_field_says_what_it_costs(window, qt_app):
    """Der Saugerabstand zeigt unter sich, was der eingestellte Wert kostet.

    Die haeufigste Frage an der Draufsicht ist, warum die Sauger nicht
    aneinanderstossen. Die Antwort ist dieses Feld - und sie ueberzeugt erst
    mit der Zahl daneben.
    """
    tab = window._tab_manager.widget_for("vacuum")

    tab.ui.min_spacing.spin.setValue(10.0)
    qt_app.processEvents()
    spaced = tab.ui.min_spacing_info.text()
    assert "0 mm" in spaced and "statt" in spaced, spaced

    tab.ui.min_spacing.spin.setValue(0.0)
    qt_app.processEvents()
    assert "stossen" in tab.ui.min_spacing_info.text()


def test_the_help_styles_follow_the_palette():
    """Das Hilfefenster faerbt seine Tabellen aus der Palette.

    Fest verdrahtete helle Untergruende ergaben in der dunklen Fassung weisse
    Schrift auf weisser Tabelle.
    """
    from app.gui.help.content import STYLE
    from app.gui.theme import PALETTE

    assert PALETTE.surface_alt in STYLE
    assert PALETTE.border in STYLE
    assert PALETTE.text in STYLE
    assert "#fdf6dd" not in STYLE or PALETTE.warning_background == "#fdf6dd"
