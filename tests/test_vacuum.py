"""Tests der Vakuum-Engine.

Geprueft wird vor allem, dass die Physik in die richtige Richtung zeigt: mehr
Vakuum mehr Kraft, mehr offene Sauger weniger Vakuum, ein groesserer Sauger mehr
Traglast. Dazu die Punkte, an denen Spezifikation 19 bis 25 ausdrueckliche
Vorgaben macht.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from app.core.result import Status
from app.core.units import lpm_to_m3s, m3s_to_m3h, mbar_to_pa
from app.dto.common import Footprint
from app.dto.package import PackageSpec
from app.dto.suction import ContactClass, RestrictorMode, RestrictorSpec, SuctionPlacement
from app.dto.vacuum import GripDirection, LeakageModel, LeakageSpec, PumpSpec, VacuumInput, VacuumPlateSpec
from app.engines.geometry.shapes import circle_rect_overlap_area_mm2
from app.engines.vacuum import contact, flow, force, layout
from app.engines.vacuum.calculator import VacuumCalculator, VacuumError
from app.engines.vacuum.leakage import workpiece_flow_m3s


@pytest.fixture
def plate():
    return VacuumPlateSpec(length_mm=800.0, width_mm=600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)


@pytest.fixture
def calculator():
    return VacuumCalculator()


@pytest.fixture
def base_request(package, plate, cup_spb2_30, settings):
    defaults = settings.get_vacuum_defaults()
    return VacuumInput(
        package=package, plate=plate, cup=cup_spb2_30,
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
        package_count=1,
    )


# Kraftmodell ------------------------------------------------------------------

@pytest.mark.parametrize(
    "cup_id,force_n",
    [("spb2_20", 6.8), ("spb2_25", 9.9), ("spb2_30", 14.4), ("spb2_40", 24.8), ("spb2_50", 34.6)],
)
def test_force_at_600mbar_matches_the_datasheet(settings, cup_id, force_n):
    """Spezifikation 25: bei -0,6 bar muss exakt der Herstellerwert herauskommen."""
    cup = settings.get_suction_cup(cup_id)
    assert force.holding_force_per_cup_n(cup, mbar_to_pa(600)) == pytest.approx(force_n, abs=0.01)


def test_force_scales_with_pressure(settings):
    cup = settings.get_suction_cup("spb2_40")
    at_600 = force.holding_force_per_cup_n(cup, mbar_to_pa(600))
    at_300 = force.holding_force_per_cup_n(cup, mbar_to_pa(300))
    assert at_300 == pytest.approx(at_600 / 2.0, rel=1e-6)


def test_force_is_capped_by_the_pull_off_limit(settings):
    """Bei sehr hohem Unterdruck begrenzt der Sauger, nicht das Vakuum.

    SPB2 40 ist die einzige Groesse des Datenblatts, bei der das mit Vakuum
    allein erreichbar ist: 40,5 N Abreisskraft entsprechen 24,8 N mal
    980/600, also rund -0,98 bar. Bei den uebrigen Groessen laege der
    rechnerische Punkt oberhalb des absoluten Vakuums und ist damit
    unerreichbar - die Abreisskraft ist eine mechanische Grenze, keine
    Vakuumgrenze.
    """
    cup = settings.get_suction_cup("spb2_40")  # Abreisskraft 40,5 N
    assert force.holding_force_per_cup_n(cup, mbar_to_pa(1000)) == pytest.approx(40.5)
    assert force.holding_force_per_cup_n(cup, mbar_to_pa(600)) == pytest.approx(24.8, abs=0.01)


def test_lateral_limit_binds_for_side_grip(settings):
    """Beim seitlichen Griff ist die Querkraft schon bei -0,6 bar bindend.

    SPB2 30 zieht dort 14,4 N, das Datenblatt nennt aber nur 12,8 N Querkraft.
    Wer seitlich greift, rechnet also mit dem kleineren Wert.
    """
    cup = settings.get_suction_cup("spb2_30")
    assert force.cup_force_limit_n(cup, GripDirection.VERTICAL) == pytest.approx(12.8)
    assert force.cup_force_limit_n(cup, GripDirection.HORIZONTAL) == pytest.approx(28.4)

    result = force.evaluate(cup, sealed_count=1, vacuum_pa=mbar_to_pa(600), mass_kg=1.0,
                            safety_factor=1.0, grip=GripDirection.VERTICAL)
    assert result.limited_by_cup_strength is True
    assert result.per_cup_n == pytest.approx(12.8)


def test_no_vacuum_no_force(settings):
    assert force.holding_force_per_cup_n(settings.get_suction_cup("spb2_30"), 0.0) == 0.0


def test_safety_factor_reduces_the_liftable_mass():
    plain = force.max_mass_kg(100.0, safety_factor=1.0)
    safe = force.max_mass_kg(100.0, safety_factor=2.0)
    assert safe == pytest.approx(plain / 2.0)
    assert plain == pytest.approx(100.0 / 9.80665)


def test_acceleration_reduces_the_liftable_mass():
    static = force.max_mass_kg(100.0, safety_factor=1.0, acceleration_ms2=0.0)
    moving = force.max_mass_kg(100.0, safety_factor=1.0, acceleration_ms2=9.80665)
    assert moving == pytest.approx(static / 2.0)


def test_side_grip_needs_more_force_than_top_grip():
    """Seitlich haengt die Last an der Reibung - die Normalkraft muss groesser sein."""
    top = force.required_force_n(10.0, 2.0, grip=GripDirection.HORIZONTAL)
    side = force.required_force_n(10.0, 2.0, grip=GripDirection.VERTICAL, friction_factor=0.5)
    assert side == pytest.approx(top / 0.5)


def test_required_cup_count_rounds_up(settings):
    cup = settings.get_suction_cup("spb2_30")  # 14,4 N bei -0,6 bar
    # 10 kg mal 9,80665 mal 1,0 = 98,07 N -> 98,07 / 14,4 = 6,81 -> 7 Sauger
    assert force.required_cup_count(10.0, cup, mbar_to_pa(600), safety_factor=1.0) == 7


def test_bigger_cup_lifts_more(settings):
    small = force.holding_force_per_cup_n(settings.get_suction_cup("spb2_20"), mbar_to_pa(600))
    large = force.holding_force_per_cup_n(settings.get_suction_cup("spb2_50"), mbar_to_pa(600))
    assert large > small * 4


# Saugerverteilung -------------------------------------------------------------

def test_automatic_layout_fills_the_plate(plate, cup_spb2_30):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate)
    assert result.count == result.max_count > 0
    assert result.columns > 1 and result.rows > 1


def test_cups_stay_on_the_plate(plate, cup_spb2_30):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate)
    radius = cup_spb2_30.outer_diameter_mm / 2.0
    for placement in result.placements:
        assert placement.center_x_mm - radius >= -1e-6
        assert placement.center_y_mm - radius >= -1e-6
        assert placement.center_x_mm + radius <= plate.length_mm + 1e-6
        assert placement.center_y_mm + radius <= plate.width_mm + 1e-6


def test_minimum_spacing_is_respected(plate, cup_spb2_30):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate)
    minimum = cup_spb2_30.outer_diameter_mm + plate.min_spacing_mm
    assert result.pitch_x_mm >= minimum - 1e-6
    assert result.pitch_y_mm >= minimum - 1e-6


def test_bigger_cup_means_fewer_positions(plate, settings):
    engine = layout.SuctionLayoutEngine()
    small = engine.distribute(settings.get_suction_cup("spb2_20"), plate)
    large = engine.distribute(settings.get_suction_cup("spb2_50"), plate)
    assert large.count < small.count


def test_bigger_plate_means_more_positions(cup_spb2_30):
    engine = layout.SuctionLayoutEngine()
    small = engine.distribute(cup_spb2_30, VacuumPlateSpec(400.0, 300.0))
    large = engine.distribute(cup_spb2_30, VacuumPlateSpec(1200.0, 900.0))
    assert large.count > small.count


def test_requested_count_is_honoured_when_it_fits(plate, cup_spb2_30):
    """Spezifikation 16: weniger Sauger muessen gleichmaessig verteilt werden."""
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate, wanted_count=24)
    assert result.count == 24
    assert result.columns * result.rows == 24
    assert result.count < result.max_count


def test_reduced_count_stays_evenly_spread(plate, cup_spb2_30):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate, wanted_count=24)
    spacings = sorted({round(p.center_x_mm, 3) for p in result.placements})
    steps = [round(b - a, 3) for a, b in zip(spacings, spacings[1:])]
    assert len(set(steps)) == 1, "Die Spalten muessen gleichen Abstand haben"


def test_awkward_count_does_not_become_a_single_line(plate, cup_spb2_30):
    """Sieben ist eine Primzahl - ein exaktes Raster waere 1 x 7.

    Eine einzelne Saugerreihe quer ueber die Platte greift kaum Kartonflaeche
    ab. Stattdessen wird ein ausgewogenes Raster gewaehlt und der ueberzaehlige
    Platz entfernt.
    """
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate, wanted_count=7)
    assert result.count == 7
    assert result.columns > 1 and result.rows > 1


@pytest.mark.parametrize("wanted", [1, 2, 3, 5, 7, 11, 13, 17, 23, 24, 31, 48])
def test_any_requested_count_is_delivered_exactly(plate, cup_spb2_30, wanted):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate, wanted_count=wanted)
    assert result.count == wanted, "Angeforderte Saugerzahl muss genau getroffen werden"


def test_more_cups_than_possible_is_reported(plate, cup_spb2_30):
    result = layout.SuctionLayoutEngine().distribute(cup_spb2_30, plate, wanted_count=100000)
    assert result.count == result.max_count
    assert result.notes, "Eine Abweichung von der Vorgabe muss gemeldet werden"


def test_plate_too_small_for_the_cup_reports_clearly(settings):
    tiny = VacuumPlateSpec(length_mm=20.0, width_mm=20.0, edge_margin_mm=25.0)
    result = layout.SuctionLayoutEngine().distribute(settings.get_suction_cup("spb2_50"), tiny)
    assert result.count == 0
    assert "zu klein" in result.notes[0]


def test_layout_is_reproducible(plate, cup_spb2_30):
    engine = layout.SuctionLayoutEngine()
    first = engine.distribute(cup_spb2_30, plate, 24)
    second = engine.distribute(cup_spb2_30, plate, 24)
    assert [(p.center_x_mm, p.center_y_mm) for p in first.placements] == \
           [(p.center_x_mm, p.center_y_mm) for p in second.placements]


# Ueberdeckung -----------------------------------------------------------------

def _cup_at(x: float, y: float, index: int = 0) -> SuctionPlacement:
    return SuctionPlacement(index=index, center_x_mm=x, center_y_mm=y, cup_id="spb2_30")


def test_cup_fully_on_the_package_is_sealed(cup_spb2_30):
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    summary = contact.classify((_cup_at(200.0, 150.0),), (package,), cup_spb2_30)
    assert summary.sealed_count == 1
    assert summary.contacts[0].contact is ContactClass.SEALED
    assert summary.contacts[0].coverage_ratio == pytest.approx(1.0)


def test_cup_far_away_is_open(cup_spb2_30):
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    summary = contact.classify((_cup_at(700.0, 500.0),), (package,), cup_spb2_30)
    assert summary.open_count == 1
    assert summary.contacts[0].contact is ContactClass.OPEN
    assert summary.contacts[0].covered_area_mm2 == 0.0


def test_cup_on_the_edge_is_partial_not_sealed(cup_spb2_30):
    """Spezifikation 19: keine Zaehlung nach Mittelpunkt.

    Der Mittelpunkt liegt hier auf dem Karton, der Dichtlippenring ragt aber
    ueber die Kante - der Sauger dichtet nicht.
    """
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    just_inside = cup_spb2_30.sealing_lip_diameter_mm / 2.0 - 2.0
    summary = contact.classify((_cup_at(just_inside, 150.0),), (package,), cup_spb2_30)

    assert summary.partial_count == 1
    assert summary.sealed_count == 0
    assert 0.0 < summary.contacts[0].coverage_ratio < 1.0


def test_partial_cup_carries_nothing_by_default(cup_spb2_30):
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    edge = cup_spb2_30.sealing_lip_diameter_mm / 2.0 - 2.0
    summary = contact.classify((_cup_at(edge, 150.0),), (package,), cup_spb2_30)
    assert summary.effective_area_mm2 == 0.0
    assert contact.bearing_count(summary) == 0


def test_partial_cup_can_be_counted_on_request(cup_spb2_30):
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    edge = cup_spb2_30.sealing_lip_diameter_mm / 2.0 - 2.0
    summary = contact.classify((_cup_at(edge, 150.0),), (package,), cup_spb2_30, count_partial_as_sealed=True)
    assert summary.effective_area_mm2 > 0.0
    assert contact.bearing_count(summary, True) == 1


def test_cup_spanning_two_packages_does_not_seal(cup_spb2_30):
    """Zwischen zwei Kartons liegt eine Fuge - dort dichtet nichts."""
    left = Footprint(0.0, 0.0, 200.0, 300.0)
    right = Footprint(200.0, 0.0, 200.0, 300.0)
    summary = contact.classify((_cup_at(200.0, 150.0),), (left, right), cup_spb2_30)
    assert summary.partial_count == 1
    assert summary.sealed_count == 0


def test_covered_area_is_exact(cup_spb2_30):
    """Die Ueberdeckung wird gerechnet, nicht geschaetzt."""
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    radius = cup_spb2_30.sealing_lip_diameter_mm / 2.0
    summary = contact.classify((_cup_at(0.0, 150.0),), (package,), cup_spb2_30)
    expected = circle_rect_overlap_area_mm2(0.0, 150.0, radius, 0.0, 0.0, 400.0, 300.0)

    assert summary.contacts[0].covered_area_mm2 == pytest.approx(expected)
    assert expected == pytest.approx(math.pi * radius * radius / 2.0, rel=1e-9)


def test_effective_area_grows_with_sealed_cups(cup_spb2_30):
    package = Footprint(0.0, 0.0, 400.0, 300.0)
    one = contact.classify((_cup_at(200.0, 150.0),), (package,), cup_spb2_30)
    two = contact.classify((_cup_at(150.0, 150.0), _cup_at(250.0, 150.0, 1)), (package,), cup_spb2_30)
    assert two.effective_area_mm2 == pytest.approx(2 * one.effective_area_mm2)


# Leckage ----------------------------------------------------------------------

def test_no_leakage_model_means_no_flow():
    assert workpiece_flow_m3s(LeakageSpec(LeakageModel.NONE), 60000.0, 1000.0, 10) == 0.0


def test_constant_leakage_scales_with_cups():
    spec = LeakageSpec(LeakageModel.CONSTANT, permeability_value=1.0)
    one = workpiece_flow_m3s(spec, 60000.0, 1000.0, 1)
    ten = workpiece_flow_m3s(spec, 60000.0, 1000.0, 10)
    assert one == pytest.approx(lpm_to_m3s(1.0))
    assert ten == pytest.approx(10 * one)


def test_area_leakage_scales_with_area_and_pressure():
    spec = LeakageSpec(LeakageModel.FLOW_PER_AREA, permeability_value=0.2, reference_vacuum_pa=60000.0)
    at_reference = workpiece_flow_m3s(spec, 60000.0, 10000.0, 5)  # 100 cm2
    assert at_reference == pytest.approx(lpm_to_m3s(0.2 * 100.0))

    half = workpiece_flow_m3s(spec, 30000.0, 10000.0, 5)
    assert half == pytest.approx(at_reference / 2.0)

    double_area = workpiece_flow_m3s(spec, 60000.0, 20000.0, 5)
    assert double_area == pytest.approx(2 * at_reference)


def test_pressure_linear_leakage_is_proportional():
    spec = LeakageSpec(LeakageModel.PRESSURE_LINEAR, permeability_value=0.003)
    low = workpiece_flow_m3s(spec, 20000.0, 10000.0, 5)
    high = workpiece_flow_m3s(spec, 60000.0, 10000.0, 5)
    assert high == pytest.approx(3 * low)


def test_every_leakage_model_is_implemented():
    for model in LeakageModel:
        spec = LeakageSpec(model, permeability_value=0.1)
        assert workpiece_flow_m3s(spec, 60000.0, 10000.0, 4) >= 0.0


# Stroemung --------------------------------------------------------------------

def test_open_cup_flow_is_in_the_expected_order_of_magnitude(settings):
    """dn 4,0 mm bei -0,6 bar liegt bei rund 7 m3/h, dn 6,1 mm bei rund 17."""
    ambient = 101325.0
    small = flow.open_cup_flow_m3s(settings.get_suction_cup("spb2_30"), RestrictorSpec(), 60000.0, ambient)
    large = flow.open_cup_flow_m3s(settings.get_suction_cup("spb2_50"), RestrictorSpec(), 60000.0, ambient)

    assert 5.0 < m3s_to_m3h(small) < 9.0
    assert 14.0 < m3s_to_m3h(large) < 20.0


def test_no_pressure_difference_no_flow(settings):
    assert flow.open_cup_flow_m3s(settings.get_suction_cup("spb2_30"), RestrictorSpec(), 0.0, 101325.0) == 0.0


def test_flow_is_choked_above_the_critical_ratio(settings):
    """Ueber dem kritischen Druckverhaeltnis waechst der Strom nicht weiter."""
    cup = settings.get_suction_cup("spb2_30")
    at_600 = flow.open_cup_flow_m3s(cup, RestrictorSpec(), 60000.0, 101325.0)
    at_800 = flow.open_cup_flow_m3s(cup, RestrictorSpec(), 80000.0, 101325.0)
    assert at_800 == pytest.approx(at_600, rel=1e-9)


def test_restrictor_reduces_the_flow(settings):
    cup = settings.get_suction_cup("spb2_50")
    without = flow.open_cup_flow_m3s(cup, RestrictorSpec(RestrictorMode.NONE), 60000.0, 101325.0)
    throttled = flow.open_cup_flow_m3s(cup, RestrictorSpec(RestrictorMode.ORIFICE, diameter_mm=1.0), 60000.0, 101325.0)
    valved = flow.open_cup_flow_m3s(
        cup, RestrictorSpec(RestrictorMode.CHECK_VALVE, check_valve_leak_ratio=0.005), 60000.0, 101325.0
    )
    assert throttled < without
    assert valved < throttled


def test_pump_curve_falls_with_vacuum():
    pump = PumpSpec(nominal_flow_m3s=0.01, max_vacuum_pa=80000.0)
    assert flow.pump_flow_m3s(pump, 0.0) == pytest.approx(0.01)
    assert flow.pump_flow_m3s(pump, 40000.0) == pytest.approx(0.005)
    assert flow.pump_flow_m3s(pump, 80000.0) == 0.0


def test_pump_curve_points_are_interpolated():
    pump = PumpSpec(nominal_flow_m3s=0.01, max_vacuum_pa=80000.0,
                    curve_points=((0.0, 0.02), (40000.0, 0.010), (80000.0, 0.0)))
    assert flow.pump_flow_m3s(pump, 20000.0) == pytest.approx(0.015)
    assert flow.pump_flow_m3s(pump, 60000.0) == pytest.approx(0.005)
    assert flow.pump_flow_m3s(pump, 999999.0) == 0.0


# Gesamtrechnung ---------------------------------------------------------------

def test_full_calculation_produces_a_consistent_result(calculator, base_request):
    result = calculator.calculate(base_request)
    assert result.total_cup_count == result.sealed_count + result.partial_count + result.open_count
    assert result.effective_area_mm2 >= 0.0
    assert result.achieved_vacuum_pa <= result.target_vacuum_pa + 1e-6
    assert result.trace is not None


def test_trace_follows_the_specified_path(calculator, base_request):
    """Spezifikation 41."""
    result = calculator.calculate(base_request, request_id=9, state_revision=3)
    names = [step.name for step in result.trace.steps]
    assert names == [
        "plattengeometrie", "paketanordnung", "saugerpositionen", "ueberdeckung",
        "wirksame_flaeche", "arbeitspunkt", "haltekraft", "maximale_masse",
    ]
    assert result.meta.request_id == 9
    assert result.meta.state_revision == 3


def test_assumptions_are_declared(calculator, base_request):
    """Spezifikation 25: jede nicht belegte Groesse muss erkennbar sein."""
    result = calculator.calculate(base_request)
    names = {a.name for a in result.trace.assumptions}
    assert "saugerkraft" in names
    assert "ausflussbeiwert" in names
    assert any(a.source == "model" for a in result.trace.assumptions)


def test_datasheet_deviation_of_spb2_30_is_declared(calculator, base_request):
    result = calculator.calculate(base_request)
    assert any(a.name == "flaechenabweichung" for a in result.trace.assumptions)


def test_open_cups_without_restrictor_collapse_the_vacuum(calculator, base_request):
    """Der Kern von Spezifikation 21: Fremdluft kostet Vakuumleistung."""
    open_plate = replace(base_request, restrictor=RestrictorSpec(RestrictorMode.NONE), requested_cup_count=24)
    valved = replace(base_request, restrictor=RestrictorSpec(RestrictorMode.CHECK_VALVE,
                                                            check_valve_leak_ratio=0.005), requested_cup_count=24)
    loose = calculator.calculate(open_plate)
    tight = calculator.calculate(valved)

    assert loose.open_count > 0
    assert loose.achieved_vacuum_pa < tight.achieved_vacuum_pa
    assert loose.max_package_mass_kg < tight.max_package_mass_kg


def test_flow_split_is_reported(calculator, base_request):
    """Spezifikation 21 fordert Q_total, Q_leak und Q_workpiece getrennt."""
    request = replace(
        base_request,
        requested_cup_count=24,
        leakage=LeakageSpec(LeakageModel.FLOW_PER_AREA, permeability_value=0.15, reference_vacuum_pa=60000.0),
    )
    result = calculator.calculate(request)

    assert result.flow.open_cups_m3s > 0.0
    assert result.flow.workpiece_m3s > 0.0
    assert result.flow.total_required_m3s == pytest.approx(
        result.flow.open_cups_m3s + result.flow.partial_cups_m3s + result.flow.workpiece_m3s
    )
    assert result.flow.leak_m3s == pytest.approx(result.flow.open_cups_m3s + result.flow.partial_cups_m3s)


def test_permeable_carton_needs_more_flow(calculator, base_request):
    sealed = calculator.calculate(base_request)
    porous = calculator.calculate(replace(
        base_request,
        leakage=LeakageSpec(LeakageModel.FLOW_PER_AREA, permeability_value=0.4, reference_vacuum_pa=60000.0),
    ))
    assert porous.flow.workpiece_m3s > sealed.flow.workpiece_m3s
    assert porous.flow.total_required_m3s > sealed.flow.total_required_m3s


def test_more_packages_mean_more_sealed_cups(calculator, base_request):
    one = calculator.calculate(base_request)
    four = calculator.calculate(replace(base_request, package_count=4))
    assert four.sealed_count > one.sealed_count
    assert four.open_count < one.open_count
    assert four.max_package_mass_kg > one.max_package_mass_kg


def test_reverse_calculation_gives_the_maximum_mass(calculator, base_request):
    """Spezifikation 24: die zentrale Rueckwaertsfrage."""
    result = calculator.calculate(replace(base_request, package_count=4))
    expected = force.max_mass_kg(
        result.force.total_holding_n, base_request.safety_factor,
        base_request.acceleration_ms2, base_request.gravity_ms2,
        base_request.grip, base_request.friction_factor,
    )
    assert result.max_package_mass_kg == pytest.approx(expected)
    assert result.max_package_mass_kg > 0.0


def test_required_cup_count_is_reported(calculator, base_request):
    """Die Umkehrung: gegebenes Gewicht, benoetigte Saugerzahl."""
    result = calculator.calculate(replace(base_request, package_count=4))
    assert result.required_cup_count > 0
    assert result.required_cup_count <= result.sealed_count


def test_safety_factor_changes_the_verdict(calculator, base_request):
    request = replace(base_request, package_count=4)
    lenient = calculator.calculate(replace(request, safety_factor=1.0))
    strict = calculator.calculate(replace(request, safety_factor=8.0))
    assert strict.max_package_mass_kg == pytest.approx(lenient.max_package_mass_kg / 8.0)


def test_status_comes_from_numbers_not_from_the_gui(calculator, base_request):
    """Spezifikation 23: die Einstufung leitet sich aus Grenzwerten ab."""
    heavy = PackageSpec(400.0, 300.0, 200.0, 400.0)
    light = PackageSpec(400.0, 300.0, 200.0, 1.0)

    assert calculator.calculate(replace(base_request, package=heavy, package_count=4)).status is Status.INSUFFICIENT
    assert calculator.calculate(replace(base_request, package=light, package_count=4)).status is Status.SAFE


def test_no_sealed_cup_is_reported_clearly(calculator, base_request):
    """Ein winziges Paket auf einer grossen Platte: nichts dichtet."""
    tiny = PackageSpec(20.0, 20.0, 50.0, 0.2)
    result = calculator.calculate(replace(base_request, package=tiny, requested_cup_count=12))
    assert result.sealed_count == 0
    assert result.max_package_mass_kg == 0.0
    assert any("traegt nichts" in w for w in result.warnings)


def test_plate_too_small_raises_a_clear_error(calculator, base_request):
    with pytest.raises(VacuumError, match="zu klein"):
        calculator.calculate(replace(base_request, plate=VacuumPlateSpec(20.0, 20.0, edge_margin_mm=25.0)))


def test_package_may_extend_beyond_the_plate(calculator, base_request):
    """Die Platte darf kleiner sein als das, was sie hebt.

    Eine Saugerplatte greift in die Mitte der Lage; die aeusseren Kartons ragen
    darueber hinaus. Wuerde die Plattengroesse die Paketanordnung beschneiden,
    liesse sich genau dieser Regelfall nicht rechnen.
    """
    huge = PackageSpec(2000.0, 1500.0, 200.0, 40.0)
    result = calculator.calculate(replace(base_request, package=huge))

    assert len(result.package_rects) == 1
    x, y, length, width = result.package_rects[0]
    # Das Muster darf das Paket um 90 Grad drehen - beide Kanten muessen
    # vorkommen, welche in welcher Richtung entscheidet die Musterschicht.
    assert {length, width} == {2000.0, 1500.0}
    assert x < 0.0 and y < 0.0, "Das Paket muss ueber die Platte hinausragen"
    # Ein Paket, das die ganze Platte ueberdeckt, dichtet jeden Sauger ab.
    assert result.open_count == 0
    assert result.sealed_count == result.total_cup_count


def test_protruding_packages_are_reported(calculator, base_request):
    """Der Hinweis muss kommen - sonst wundert man sich ueber offene Sauger."""
    wide = PackageSpec(1400.0, 300.0, 200.0, 9.0)
    result = calculator.calculate(replace(base_request, package=wide, package_count=2))
    assert any("ragen ueber die Platte hinaus" in w for w in result.warnings)


def test_result_is_reproducible(calculator, base_request):
    """Spezifikation 39."""
    first = calculator.calculate(base_request)
    second = calculator.calculate(base_request)
    assert first.achieved_vacuum_pa == second.achieved_vacuum_pa
    assert first.max_package_mass_kg == second.max_package_mass_kg
    assert [(p.center_x_mm, p.center_y_mm) for p in first.placements] == \
           [(p.center_x_mm, p.center_y_mm) for p in second.placements]


def test_cancellation_stops_the_run(calculator, base_request):
    from app.core.cancellation import CancellationToken, CancelledError

    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        calculator.calculate(base_request, token=token)


def test_pattern_from_tab_two_is_reused(calculator, base_request):
    """Spezifikation 18: Tab 3 verwendet das Muster aus Tab 2."""
    grid = calculator.calculate(replace(base_request, package_count=4, pattern_id="uniform_grid"))
    bond = calculator.calculate(replace(base_request, package_count=4, pattern_id="running_bond"))
    assert grid.package_rects != bond.package_rects


def test_side_grip_lowers_the_liftable_mass(calculator, base_request):
    request = replace(base_request, package_count=4)
    top = calculator.calculate(request)
    side = calculator.calculate(replace(request, grip=GripDirection.VERTICAL, friction_factor=0.5))
    assert side.max_package_mass_kg == pytest.approx(top.max_package_mass_kg * 0.5, rel=0.3)
    assert side.max_package_mass_kg < top.max_package_mass_kg


def test_acceleration_lowers_the_liftable_mass(calculator, base_request):
    request = replace(base_request, package_count=4)
    static = calculator.calculate(request)
    moving = calculator.calculate(replace(request, acceleration_ms2=5.0))
    assert moving.max_package_mass_kg < static.max_package_mass_kg


# Paketanordnung ----------------------------------------------------------------

def _grouped(rects) -> set[tuple[float, float]]:
    return {(round(f.x_mm, 3), round(f.y_mm, 3)) for f in rects}


@pytest.mark.parametrize(
    "strategy", ["uniform_grid", "running_bond", "checkerboard", "guillotine_mix"]
)
def test_package_layout_grows_from_the_inside_outwards(strategy):
    """Eine hoehere Stueckzahl ergaenzt die Anordnung, statt sie neu zu wuerfeln.

    Die Gruppe rueckt dabei nach, damit ihr Schwerpunkt in der Plattenmitte
    bleibt - geprueft wird deshalb nicht auf gleiche Koordinaten, sondern
    darauf, dass sich die neue Anordnung aus der alten durch eine gemeinsame
    Verschiebung plus ein Paket ergibt.
    """
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(200.0, 150.0, 120.0, 2.0)

    for count in range(1, 13):
        before, _ = layout.package_layout(package, plate, count, strategy=strategy)
        after, _ = layout.package_layout(package, plate, count + 1, strategy=strategy)
        assert len(after) == count + 1

        old_positions = _grouped(before)
        new_positions = _grouped(after)
        reference = sorted(old_positions)[0]

        matched = False
        for candidate in sorted(new_positions):
            dx = candidate[0] - reference[0]
            dy = candidate[1] - reference[1]
            shifted = {(round(x + dx, 3), round(y + dy, 3)) for x, y in old_positions}
            if shifted <= new_positions:
                matched = True
                break
        assert matched, (
            strategy + ": beim Wechsel von " + str(count) + " auf " + str(count + 1)
            + " Paketen wird die Anordnung neu gewuerfelt"
        )


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 9, 12])
def test_package_group_is_centred_by_its_centre_of_mass(count):
    """Der Schwerpunkt muss unter der Plattenmitte liegen.

    Nach dem umschliessenden Rechteck zu zentrieren waere einfacher, laesst die
    Last bei unsymmetrischen Gruppen aber seitlich haengen - vier Pakete in
    L-Form um bis zu eine halbe Paketlaenge. Am Greifer entsteht daraus ein
    Kippmoment.
    """
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(200.0, 150.0, 120.0, 2.0)
    rects, _notes = layout.package_layout(package, plate, count)

    centre_x = sum(f.x_mm + f.length_mm / 2.0 for f in rects) / len(rects)
    centre_y = sum(f.y_mm + f.width_mm / 2.0 for f in rects) / len(rects)

    assert centre_x == pytest.approx(plate.length_mm / 2.0, abs=1e-6)
    assert centre_y == pytest.approx(plate.width_mm / 2.0, abs=1e-6)


def test_package_layout_uses_the_pattern_from_tab_two():
    """Spezifikation 18: das Muster aus der Palettierung ordnet auch hier an."""
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(200.0, 150.0, 120.0, 2.0)

    grid, _ = layout.package_layout(package, plate, 9, strategy="uniform_grid")
    bond, _ = layout.package_layout(package, plate, 9, strategy="running_bond")

    assert _grouped(grid) != _grouped(bond)

    # Im Laeuferverband sind die Reihen gegeneinander versetzt.
    rows: dict[float, list[float]] = {}
    for footprint in bond:
        rows.setdefault(round(footprint.y_mm, 3), []).append(footprint.x_mm)
    starts = [min(xs) for _y, xs in sorted(rows.items())]
    assert len(set(round(s, 3) for s in starts)) > 1


def test_package_layout_is_reproducible():
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(200.0, 150.0, 120.0, 2.0)
    first, _ = layout.package_layout(package, plate, 6, strategy="checkerboard")
    second, _ = layout.package_layout(package, plate, 6, strategy="checkerboard")
    assert first == second


def test_the_plate_area_is_filled_before_packages_hang_over():
    """Erst belegen, was unter der Platte liegt - dann darueber hinaus.

    Die Reihenfolge nach blossem Abstand zur Mitte waehlt bei einem Paket
    200 x 150 mm lieber die naechste Reihe (150 mm) als die naechste Spalte
    (200 mm) und baut einen hohen schmalen Stapel, der oben und unten
    ueberhaengt, waehrend links und rechts Plattenflaeche frei bleibt.
    """
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(200.0, 150.0, 120.0, 2.0)

    def under_plate(rects) -> int:
        return sum(
            1 for f in rects
            if f.x_mm >= -1e-6 and f.y_mm >= -1e-6
            and f.x_mm + f.length_mm <= plate.length_mm + 1e-6
            and f.y_mm + f.width_mm <= plate.width_mm + 1e-6
        )

    # 4 x 4 Pakete passen kantenbuendig unter die Platte.
    for count in (1, 4, 12, 16):
        rects, _ = layout.package_layout(package, plate, count)
        assert under_plate(rects) == count, (
            str(count) + " Pakete muessten vollstaendig unter die Platte passen"
        )

    # Darueber hinaus haengt ueber, was nicht mehr hineinpasst.
    rects, notes = layout.package_layout(package, plate, 20)
    assert under_plate(rects) == 16
    assert any("ragen ueber die Platte hinaus" in note for note in notes)


def test_the_package_group_grows_sideways_not_upwards():
    """Was nicht mehr unter die Platte passt, legt sich seitlich an.

    Unter die Platte passen 2 x 2 Pakete. Das fuenfte bis achte gehoert daneben
    und nicht darueber: eine Ladung, die in die Hoehe waechst, ragt oben und
    unten hinaus, waehrend links und rechts Platz bleibt.

    Gemessen wird das umschliessende Rechteck. Es wird breiter, seine Hoehe
    bleibt die der Platte.
    """
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(400.0, 300.0, 200.0, 5.0)

    def extent(rects) -> tuple[float, float]:
        width = max(f.x_mm + f.length_mm for f in rects) - min(f.x_mm for f in rects)
        height = max(f.y_mm + f.width_mm for f in rects) - min(f.y_mm for f in rects)
        return width, height

    previous_width = 0.0
    for count in (4, 5, 6, 7, 8):
        rects, _ = layout.package_layout(package, plate, count)
        width, height = extent(rects)
        assert height == pytest.approx(plate.width_mm), (
            str(count) + " Pakete bauen sich in die Hoehe auf"
        )
        assert width >= previous_width
        previous_width = width

    assert previous_width == pytest.approx(4 * package.length_mm)


def test_two_packages_lie_next_to_each_other():
    """Zwei Pakete unter einer Platte, auf der vier Platz haben: nebeneinander."""
    plate = VacuumPlateSpec(800.0, 600.0)
    package = PackageSpec(400.0, 300.0, 200.0, 5.0)

    rects, _ = layout.package_layout(package, plate, 2)

    assert len({round(f.y_mm, 3) for f in rects}) == 1
    assert len({round(f.x_mm, 3) for f in rects}) == 2


def test_growth_direction_does_not_depend_on_the_package_shape():
    """Auch ein hochkant stehendes Paket waechst seitlich.

    Der Abstand in Millimetern wuerde hier die Reihe bevorzugen, sobald das
    Paket tiefer als breit ist. Gemessen wird deshalb in Rasterzellen.
    """
    plate = VacuumPlateSpec(600.0, 800.0)
    package = PackageSpec(300.0, 400.0, 200.0, 5.0)

    rects, _ = layout.package_layout(package, plate, 6)
    columns = len({round(f.x_mm, 3) for f in rects})
    rows = len({round(f.y_mm, 3) for f in rects})

    assert columns > rows


# Rastermass ---------------------------------------------------------------------

def test_the_result_reports_the_grid_pitch(calculator, base_request):
    """Das Rastermass steht im Ergebnis, damit die Zeichnung es zeigen kann.

    Es nachzumessen waere Sache der Engine, nicht der Anzeige
    (Spezifikation 37) - und aus den Mittelpunkten liesse es sich nur mit
    einem Vergleich jedes Saugers mit jedem zurueckgewinnen.
    """
    result = calculator.calculate(replace(base_request, arrangement_id="grid_dense"))

    expected = result.cup.outer_diameter_mm + result.plate.min_spacing_mm
    assert result.pitch_x_mm == pytest.approx(expected)
    assert result.pitch_y_mm == pytest.approx(expected)


def test_without_a_minimum_spacing_the_cups_touch(calculator, base_request, plate):
    """Ohne Mindestabstand stossen die Aussenkanten aneinander.

    Das ist die dichteste Bestueckung, die die Geometrie zulaesst: der
    Mittenabstand ist dann genau das Aussenmass unter Vakuum. Wer mehr Sauger
    auf die Platte bringen will, hat hier den Hebel.
    """
    touching = replace(plate, min_spacing_mm=0.0)
    dense = calculator.calculate(
        replace(base_request, plate=touching, arrangement_id="grid_dense")
    )
    spaced = calculator.calculate(replace(base_request, arrangement_id="grid_dense"))

    assert dense.pitch_x_mm == pytest.approx(dense.cup.outer_diameter_mm)
    assert dense.total_cup_count > spaced.total_cup_count, (
        "ohne Mindestabstand muessen mehr Sauger auf die Platte passen"
    )

    # Und kein Paar kommt sich naeher als das Aussenmass - sonst ueberlappten
    # sich zwei Sauger.
    centers = [(p.center_x_mm, p.center_y_mm) for p in dense.placements]
    closest = min(
        math.hypot(ax - bx, ay - by)
        for index, (ax, ay) in enumerate(centers)
        for bx, by in centers[index + 1:]
    )
    assert closest >= dense.cup.outer_diameter_mm - 1e-6
