"""Tests des Vakuumverlaufs.

Geprueft wird vor allem das eine, woran diese Rechnung scheitern koennte:
dass sie in einen ANDEREN Endwert laeuft als die Platte nebenan. Dazu die
Richtungen - mehr Volumen mehr Zeit, mehr Drehzahl mehr Strom - und die
Stellen, an denen die Frequenz vom Aehnlichkeitsgesetz abweicht.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.units import m3s_to_m3h, mbar_to_pa, pa_to_mbar
from app.vacuum import evacuation, physics
from app.vacuum.calculator import VacuumCalculator
from app.vacuum.models import SystemVolumeSpec, VacuumInput, VacuumPlateSpec


@pytest.fixture
def plate():
    return VacuumPlateSpec(length_mm=800.0, width_mm=600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)


@pytest.fixture
def anfrage(package, plate, cup_spb2_30, settings):
    defaults = settings.get_vacuum_defaults()
    return VacuumInput(
        package=package, plate=plate, cup=cup_spb2_30,
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
        target_vacuum_pa=defaults.target_vacuum_pa,
        package_count=1,
    )


@pytest.fixture
def ergebnis(anfrage):
    return VacuumCalculator().calculate(anfrage)


# Das Volumen ------------------------------------------------------------------

def test_the_volume_is_reported_in_three_parts(plate):
    """Welcher Posten die Zeit bestimmt, ist die erste Frage an die Rechnung."""
    volumen = SystemVolumeSpec(box_height_mm=80.0, hose_length_m=10.0,
                               hose_diameter_mm=100.0, extra_volume_l=5.0)
    kasten, schlauch, zusatz = evacuation.system_volume_m3(plate, volumen)

    # 800 x 600 x 80 mm
    assert kasten == pytest.approx(0.0384)
    # 10 m Rohr, 50 mm Radius: pi * 0,05^2 * 10
    assert schlauch == pytest.approx(0.0785398, rel=1e-5)
    assert zusatz == pytest.approx(0.005)


def test_negative_entries_do_not_shrink_the_volume(plate):
    """Eine negative Laenge ist keine Eingabe, sondern ein Tippfehler."""
    volumen = SystemVolumeSpec(box_height_mm=-80.0, hose_length_m=-10.0,
                               hose_diameter_mm=100.0, extra_volume_l=-5.0)
    assert evacuation.system_volume_m3(plate, volumen) == (0.0, 0.0, 0.0)


# Der Endwert ------------------------------------------------------------------

def test_the_curve_ends_where_the_plate_says_it_does(anfrage, ergebnis):
    """Der wichtigste Test dieser Datei.

    Zwei Tabs, die dieselbe Platte verschieden beurteilen, sind schlimmer als
    ein Tab weniger. Beide benutzen deshalb dieselben zwei Funktionen -
    physics.demand_m3s() und physics.balance_vacuum_pa() - und muessen auf
    denselben Punkt kommen.
    """
    kurve = evacuation.curve(anfrage, ergebnis, SystemVolumeSpec(), 50.0)

    assert kurve.final_vacuum_pa == pytest.approx(ergebnis.achieved_vacuum_pa, abs=1.0), (
        "Verlauf endet bei " + format(pa_to_mbar(kurve.final_vacuum_pa), ".1f")
        + " mbar, die Platte meldet "
        + format(pa_to_mbar(ergebnis.achieved_vacuum_pa), ".1f") + " mbar"
    )


def test_the_curve_rises_and_never_turns_back(anfrage, ergebnis):
    """Zeit und Vakuum steigen beide - sonst waere die Quadratur kaputt."""
    kurve = evacuation.curve(anfrage, ergebnis, SystemVolumeSpec(), 50.0)

    assert len(kurve.points) > 100
    assert kurve.points[0].time_s == 0.0
    assert kurve.points[0].vacuum_pa == 0.0
    for vorher, nachher in zip(kurve.points, kurve.points[1:]):
        assert nachher.time_s > vorher.time_s
        assert nachher.vacuum_pa > vorher.vacuum_pa
    assert kurve.points[-1].vacuum_pa < kurve.final_vacuum_pa, (
        "Der Endwert wird asymptotisch erreicht - genau dort darf die Kurve "
        "nicht ankommen"
    )
    assert 0.0 < kurve.time_to_90_s < kurve.time_to_99_s


def test_the_time_matches_the_closed_form_without_leakage(plate, cup_spb2_30):
    """Die Zeit selbst, nicht nur ihre Richtung.

    Ohne Leckage laesst sich die Gleichung von Hand loesen. Mit der geraden
    Kennlinie S(dp) = S0 * (1 - dp/dp_max) wird aus

        d(dp)/dt = (p_umg / V) * S(dp)

    eine Exponentialfunktion mit der Zeitkonstanten

        tau = V * dp_max / (p_umg * S0)      und      t(90%) = tau * ln(10)

    Diese Probe faengt, was die Richtungstests nicht faengen: einen falschen
    Faktor. Ohne p_umg im Nenner waeren alle Zeiten um fuenf Zehnerpotenzen
    daneben - und jeder Vergleich "doppeltes Volumen, doppelte Zeit" bliebe
    trotzdem gruen.
    """
    import math

    from app.domain.results import CalculationMeta
    from app.vacuum.models import (
        LeakageModel, LeakageSpec, PumpSpec, RestrictorMode, RestrictorSpec,
        VacuumResult,
    )

    umgebung = 101325.0
    strom = 0.1
    endvakuum = mbar_to_pa(390.0)
    volumen_m3 = 0.1

    anfrage = VacuumInput(
        package=None, plate=plate, cup=cup_spb2_30,
        pump=PumpSpec(nominal_flow_m3s=strom, max_vacuum_pa=endvakuum),
        leakage=LeakageSpec(model=LeakageModel.NONE),
        restrictor=RestrictorSpec(mode=RestrictorMode.NONE),
        target_vacuum_pa=endvakuum,
        ambient_pa=umgebung,
    )
    # Eine Platte ohne einen einzigen offenen Sauger - dann ist der Bedarf
    # auf dem ganzen Weg null.
    ergebnis = VacuumResult(
        meta=CalculationMeta(module_id="vacuum", algorithm_version="1.0"),
        plate=plate, cup=cup_spb2_30,
        sealed_count=10, partial_count=0, open_count=0,
        effective_area_mm2=0.0,
    )
    kurve = evacuation.curve(
        anfrage, ergebnis,
        SystemVolumeSpec(box_height_mm=0.0, hose_length_m=0.0,
                         extra_volume_l=volumen_m3 * 1000.0),
        50.0,
    )

    tau = volumen_m3 * endvakuum / (umgebung * strom)
    assert kurve.time_to_90_s == pytest.approx(tau * math.log(10.0), rel=0.01), (
        "Gerechnet " + format(kurve.time_to_90_s, ".4f") + " s, von Hand "
        + format(tau * math.log(10.0), ".4f") + " s"
    )
    assert kurve.time_to_99_s == pytest.approx(tau * math.log(100.0), rel=0.01)


# Die Richtungen ---------------------------------------------------------------

def test_twice_the_volume_takes_twice_the_time(anfrage, ergebnis):
    """Die Zeit ist dem Volumen proportional - das steht so in der Gleichung."""
    klein = evacuation.curve(anfrage, ergebnis,
                             SystemVolumeSpec(box_height_mm=0.0, hose_length_m=0.0,
                                              extra_volume_l=50.0), 50.0)
    gross = evacuation.curve(anfrage, ergebnis,
                             SystemVolumeSpec(box_height_mm=0.0, hose_length_m=0.0,
                                              extra_volume_l=100.0), 50.0)

    assert gross.time_to_90_s == pytest.approx(2.0 * klein.time_to_90_s, rel=1e-6)
    assert gross.final_vacuum_pa == pytest.approx(klein.final_vacuum_pa), (
        "Das Volumen aendert die Zeit, nicht den Endwert"
    )


def test_without_a_volume_there_is_no_time_axis(anfrage, ergebnis):
    """Und die Rechnung sagt das, statt eine leere Kurve zu zeigen."""
    kurve = evacuation.curve(
        anfrage, ergebnis,
        SystemVolumeSpec(box_height_mm=0.0, hose_length_m=0.0, extra_volume_l=0.0),
        50.0,
    )

    assert kurve.points == ()
    assert any("Systemvolumen" in note for note in kurve.notes), kurve.notes


# Die Frequenz -----------------------------------------------------------------

def test_flow_follows_the_speed_and_the_end_vacuum_does_not(anfrage):
    """Die Gegenprobe an den Datenblaettern, in eine Regel gegossen.

    Saugvermoegen proportional zur Drehzahl: 28 Geraete, Mittel 1,200 fuer
    60/50 Hz - das Aehnlichkeitsgesetz stimmt. Endvakuum quadratisch: Mittel
    0,941 statt 1,440 - es stimmt NICHT. Oberhalb der Bezugsfrequenz bleibt
    das Endvakuum deshalb beim Datenblattwert.
    """
    pumpe = replace(anfrage.pump, nominal_flow_m3s=0.1, max_vacuum_pa=mbar_to_pa(390.0))

    halb = physics.pump_at_frequency(pumpe, 25.0)
    assert halb.nominal_flow_m3s == pytest.approx(0.05)
    assert pa_to_mbar(halb.max_vacuum_pa) == pytest.approx(97.5), (
        "Unterhalb 50 Hz gilt das Quadratgesetz"
    )

    schnell = physics.pump_at_frequency(pumpe, 100.0)
    assert schnell.nominal_flow_m3s == pytest.approx(0.2)
    assert schnell.max_vacuum_pa == pytest.approx(pumpe.max_vacuum_pa), (
        "Oberhalb 50 Hz wird das Endvakuum beim Datenblattwert gedeckelt - "
        "mit dem Quadratgesetz stuenden hier 1560 mbar, also mehr als der "
        "Luftdruck"
    )


def test_the_curve_points_are_scaled_with_the_frequency(anfrage):
    """Auch eine Kennlinie aus Stuetzpunkten wird mitgezogen."""
    pumpe = replace(anfrage.pump, nominal_flow_m3s=0.1, max_vacuum_pa=mbar_to_pa(400.0),
                    curve_points=((0.0, 0.1), (mbar_to_pa(400.0), 0.0)))

    halb = physics.pump_at_frequency(pumpe, 25.0)
    assert halb.curve_points[0] == pytest.approx((0.0, 0.05))
    assert halb.curve_points[1][0] == pytest.approx(mbar_to_pa(100.0))
    assert halb.curve_points[1][1] == pytest.approx(0.0)


def test_more_frequency_is_faster_and_not_deeper(anfrage, ergebnis):
    """Ueber 50 Hz kauft die Drehzahl Zeit, kein Vakuum."""
    langsam = evacuation.curve(anfrage, ergebnis, SystemVolumeSpec(), 50.0)
    schnell = evacuation.curve(anfrage, ergebnis, SystemVolumeSpec(), 100.0)

    assert m3s_to_m3h(schnell.nominal_flow_m3s) == pytest.approx(
        2.0 * m3s_to_m3h(langsam.nominal_flow_m3s))
    assert schnell.time_to_90_s < langsam.time_to_90_s
    assert schnell.max_vacuum_pa == pytest.approx(langsam.max_vacuum_pa), (
        "Das Endvakuum des Datenblatts ist die Grenze"
    )
    assert schnell.final_vacuum_pa > langsam.final_vacuum_pa, (
        "Etwas tiefer geht es doch: der staerkere Erzeuger kommt naeher an "
        "sein Endvakuum heran, weil die Leckage relativ kleiner wird"
    )


def test_a_weak_producer_reaches_no_vacuum_and_says_so(anfrage, ergebnis):
    """Ohne Vakuum keine Kurve - und ein Satz, warum."""
    schwach = replace(anfrage.pump, nominal_flow_m3s=0.0, max_vacuum_pa=mbar_to_pa(390.0))
    kurve = evacuation.curve(replace(anfrage, pump=schwach), ergebnis,
                             SystemVolumeSpec(), 50.0)

    assert kurve.points == ()
    assert kurve.final_vacuum_pa == 0.0
    assert any("Leckage" in note for note in kurve.notes), kurve.notes
