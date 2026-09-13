"""Tests der Konfigurationsschicht.

Schwerpunkt ist das Verhalten bei defekten Daten: Spezifikation 27 verlangt,
dass ein fehlerhafter Eintrag gemeldet wird, ohne die Anwendung zu stoppen.
"""

from __future__ import annotations

import json

import pytest

from app.config.loader import ConfigLoader, strip_comments
from app.config.schema import parse_pallets, parse_suction_cups, parse_vacuum_defaults
from app.config.settings_service import SettingsService
from app.core.errors import Severity
from app.dto.suction import RestrictorMode
from app.dto.vacuum import GripDirection, LeakageModel


# Mitgelieferte Dateien ---------------------------------------------------------

def test_shipped_configuration_loads_without_problems(settings, reporter):
    status = settings.status()
    assert status.ok, "Mitgelieferte Konfiguration muss fehlerfrei laden: " + str(status)
    assert status.pallet_count >= 4
    assert status.pattern_count >= 8
    assert status.cup_count >= 24


def test_all_datasheet_sizes_are_present(settings):
    """Vier Baureihen, jede vollstaendig."""
    ids = {c.id for c in settings.get_suction_cups()}
    expected = (
        {"spb2_" + str(n) for n in (20, 25, 30, 40, 50)}
        | {"spb1_" + str(n) for n in (10, 15, 20, 25, 30, 40, 50, 60, 80)}
        | {"spb2f_" + str(n) for n in (15, 20, 25, 30, 40, 50)}
        | {"spb4_" + str(n) for n in (20, 30, 40, 50)}
    )
    assert ids == expected


def test_every_family_is_complete(settings):
    families: dict[str, int] = {}
    for cup in settings.get_suction_cups():
        families[cup.family] = families.get(cup.family, 0) + 1
    assert families == {"SPB2": 5, "SPB1": 9, "SPB2f": 6, "SPB4": 4}


@pytest.mark.parametrize(
    "cup_id,force_n,d2_mm,ds_mm,dn_mm",
    [
        ("spb1_10", 1.5, 5.6, 9.8, 1.8),
        ("spb1_80", 166.0, 56.0, 81.4, 6.1),
        ("spb2f_30", 12.8, 7.2, 30.0, 4.0),
        ("spb2f_50", 41.0, 21.0, 49.7, 4.0),
        ("spb4_20", 8.0, 13.5, 21.4, 4.0),
        ("spb4_50", 50.0, 30.0, 50.3, 4.0),
    ],
)
def test_new_family_values_match_the_datasheets(settings, cup_id, force_n, d2_mm, ds_mm, dn_mm):
    """Stichproben aus den drei ergaenzten Baureihen."""
    cup = settings.get_suction_cup(cup_id)
    assert cup.theoretical_force_n == force_n
    assert cup.effective_diameter_mm == d2_mm
    assert cup.sealing_lip_diameter_mm == ds_mm
    assert cup.bore_diameter_mm == dn_mm
    assert cup.reference_vacuum_pa == 60000.0


def test_families_without_a_pull_off_force_declare_none(settings):
    """SPB2f und SPB4 nennen keine Abreisskraft beim Bezugsdruck.

    Sie auf -0,6 bar hochzurechnen waere eine Erfindung (Spezifikation 25).
    Null steht fuer "kein Wert angegeben"; die Software verzichtet dann auf die
    mechanische Grenzwertpruefung.
    """
    for cup in settings.get_suction_cups():
        if cup.family in ("SPB2f", "SPB4"):
            assert cup.pull_off_force_n == 0.0
            assert cup.lateral_force_n == 0.0
        else:
            assert cup.pull_off_force_n > 0.0


def test_d2_agrees_with_the_datasheet_force_only_for_spb2(settings):
    """Der Abgleich d2 gegen Datenblattkraft geht nur bei SPB2 auf.

    Bei den uebrigen Baureihen ist der Faltendurchmesser nicht die
    kraftuebertragende Flaeche - bei SPB2f 30 bis 50 um bis zu 81 Prozent
    daneben. Das ist unkritisch, weil die Software ausschliesslich mit der
    Datenblattkraft rechnet; der Test haelt den Befund fest, damit niemand
    spaeter auf d2 umstellt.
    """
    for cup in settings.get_suction_cups():
        deviation = abs(cup.force_area_deviation_pct)
        if cup.family == "SPB2":
            assert deviation < 7.0, cup.id + " weicht um " + format(deviation, ".1f") + " % ab"

    grosse_abweichung = [
        c.id for c in settings.get_suction_cups() if abs(c.force_area_deviation_pct) > 25.0
    ]
    assert set(grosse_abweichung) == {"spb2f_30", "spb2f_40", "spb2f_50"}


@pytest.mark.parametrize(
    "cup_id,force_n,d2_mm,bore_mm",
    [
        ("spb2_20", 6.8, 12.0, 4.0),
        ("spb2_25", 9.9, 14.5, 4.0),
        ("spb2_30", 14.4, 16.9, 4.0),
        ("spb2_40", 24.8, 22.9, 6.1),
        ("spb2_50", 34.6, 27.1, 6.1),
    ],
)
def test_datasheet_values_are_carried_through_unchanged(settings, cup_id, force_n, d2_mm, bore_mm):
    """Spezifikation 25: keine erfundenen Herstellerkennwerte."""
    cup = settings.get_suction_cup(cup_id)
    assert cup.theoretical_force_n == force_n
    assert cup.effective_diameter_mm == d2_mm
    assert cup.bore_diameter_mm == bore_mm


@pytest.mark.parametrize("cup_id", ["spb2_20", "spb2_25", "spb2_40", "spb2_50"])
def test_effective_area_reproduces_datasheet_force(settings, cup_id):
    """d2-Flaeche mal 60000 Pa trifft die Datenblattkraft auf unter ein Prozent."""
    cup = settings.get_suction_cup(cup_id)
    geometric_n = 60000.0 * cup.effective_area_mm2 / 1_000_000.0
    assert geometric_n == pytest.approx(cup.theoretical_force_n, rel=0.01)


def test_spb2_30_deviation_is_known_and_bounded(settings):
    """SPB2 30 weicht als einzige Groesse ab - das ist bekannt und begrenzt."""
    cup = settings.get_suction_cup("spb2_30")
    assert -8.0 < cup.force_area_deviation_pct < -5.0


def test_geometry_is_ordered_per_cup(settings):
    for cup in settings.get_suction_cups():
        assert cup.effective_diameter_mm < cup.sealing_lip_diameter_mm <= cup.outer_diameter_mm


def test_vacuum_defaults_are_complete(settings):
    defaults = settings.get_vacuum_defaults()
    assert defaults.plate.length_mm > 0 and defaults.plate.width_mm > 0
    assert defaults.safety_factor >= 1.0
    assert defaults.grip is GripDirection.HORIZONTAL
    assert defaults.pump.nominal_flow_m3s > 0
    assert len(defaults.leakage_presets) >= 4
    assert any(p.spec.model is LeakageModel.FLOW_PER_AREA for p in defaults.leakage_presets)


def test_overhang_widens_the_usable_footprint(settings):
    plain = settings.get_pallet("euro_1200x800")
    wide = settings.get_pallet("euro_overhang_1200x800")
    assert plain.usable_length_mm == 1200.0
    assert wide.usable_length_mm == 1240.0
    assert wide.usable_area_mm2 > plain.usable_area_mm2


# Fehlertoleranz ----------------------------------------------------------------

def test_missing_file_is_reported_not_fatal(tmp_path, reporter):
    loader = ConfigLoader(tmp_path, reporter)
    result = loader.load("pallets.json")
    assert result.ok is False and result.data == {}
    assert reporter.problems.count(Severity.WARNING) == 1


def test_broken_json_is_reported_not_fatal(tmp_path, reporter):
    (tmp_path / "pallets.json").write_text("{ das ist kein json", encoding="utf-8")
    result = ConfigLoader(tmp_path, reporter).load("pallets.json")
    assert result.ok is False
    assert "kein gueltiges JSON" in result.message


def test_service_falls_back_to_builtin_data(tmp_path, reporter):
    """Leeres Verzeichnis: die Anwendung bleibt bedienbar."""
    service = SettingsService(tmp_path, reporter)
    status = service.load()

    assert status.ok is False
    assert len(service.get_pallets()) >= 1
    assert len(service.get_patterns()) >= 1
    assert len(service.get_suction_cups()) >= 1
    assert set(status.used_builtin) == {"pallets.json", "pallet_patterns.json", "suction_cups.json"}


def test_one_bad_entry_does_not_drop_the_others(reporter):
    data = {
        "pallets": [
            {"id": "gut", "name": "Gut", "length_mm": 1200, "width_mm": 800,
             "max_load_kg": 1000, "max_load_height_mm": 1500},
            {"id": "schlecht", "name": "Negativ", "length_mm": -5, "width_mm": 800,
             "max_load_kg": 1000, "max_load_height_mm": 1500},
            {"id": "unvollstaendig", "name": "Ohne Breite", "length_mm": 1200,
             "max_load_kg": 1000, "max_load_height_mm": 1500},
        ]
    }
    pallets = parse_pallets(data, reporter)
    assert [p.id for p in pallets] == ["gut"]
    assert reporter.problems.count(Severity.WARNING) == 2


def test_duplicate_ids_are_skipped(reporter):
    data = {
        "pallets": [
            {"id": "doppelt", "length_mm": 1200, "width_mm": 800, "max_load_kg": 1, "max_load_height_mm": 1},
            {"id": "doppelt", "length_mm": 1000, "width_mm": 800, "max_load_kg": 1, "max_load_height_mm": 1},
        ]
    }
    pallets = parse_pallets(data, reporter)
    assert len(pallets) == 1 and pallets[0].length_mm == 1200


def test_cup_with_impossible_geometry_is_rejected(reporter):
    data = {
        "suction_cups": [
            {"id": "kaputt", "nominal_diameter_mm": 30, "effective_diameter_mm": 40,
             "bore_diameter_mm": 4, "theoretical_force_n": 14.4},
        ]
    }
    assert parse_suction_cups(data, reporter) == ()
    assert reporter.problems.count(Severity.WARNING) == 1


def test_unknown_enum_value_drops_only_that_entry(reporter):
    from app.config.schema import parse_patterns

    data = {
        "patterns": [
            {"id": "gut", "strategy": "uniform_grid", "z_mode": "mirror"},
            {"id": "schlecht", "strategy": "uniform_grid", "z_mode": "purzelbaum"},
        ]
    }
    patterns = parse_patterns(data, reporter)
    assert [p.id for p in patterns] == ["gut"]


def test_empty_vacuum_section_yields_usable_defaults(reporter):
    defaults = parse_vacuum_defaults({}, reporter)
    assert defaults.plate.length_mm > 0
    assert defaults.restrictor.mode is RestrictorMode.NONE
    assert defaults.leakage.model is LeakageModel.NONE


def test_newer_config_version_warns_but_loads(tmp_path, reporter):
    payload = {"version": 99, "pallets": [
        {"id": "a", "length_mm": 1200, "width_mm": 800, "max_load_kg": 1, "max_load_height_mm": 1}
    ]}
    (tmp_path / "pallets.json").write_text(json.dumps(payload), encoding="utf-8")
    service = SettingsService(tmp_path, reporter)
    service.load()

    assert len(service.get_pallets()) == 1
    assert any("Version 99" in e.message for e, _ in reporter.problems.entries())


def test_comment_keys_are_stripped():
    cleaned = strip_comments({"_comment": "weg", "a": 1, "nested": {"_x": 2, "b": 3},
                              "list": [{"_y": 4, "c": 5}]})
    assert cleaned == {"a": 1, "nested": {"b": 3}, "list": [{"c": 5}]}


def test_reload_replaces_the_catalog(tmp_path, reporter):
    path = tmp_path / "pallets.json"
    path.write_text(json.dumps({"pallets": [
        {"id": "erste", "length_mm": 1200, "width_mm": 800, "max_load_kg": 1, "max_load_height_mm": 1}
    ]}), encoding="utf-8")
    service = SettingsService(tmp_path, reporter)
    service.load()
    assert service.get_pallet("erste") is not None

    path.write_text(json.dumps({"pallets": [
        {"id": "zweite", "length_mm": 1000, "width_mm": 600, "max_load_kg": 1, "max_load_height_mm": 1}
    ]}), encoding="utf-8")
    service.load()
    assert service.get_pallet("erste") is None
    assert service.get_pallet("zweite") is not None


def test_listeners_are_called_on_reload(tmp_path, reporter):
    calls: list[int] = []
    service = SettingsService(tmp_path, reporter)
    service.add_listener(lambda: calls.append(1))
    service.load()
    service.load()
    assert len(calls) == 2
