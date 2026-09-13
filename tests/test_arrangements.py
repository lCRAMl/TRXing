"""Tests der Saugermuster.

Die harte Zusage jedes Musters: kein Sauger ragt ueber die nutzbare Flaeche
hinaus, und keine zwei Sauger kommen sich naeher als der geforderte
Mindestabstand. Beides ist keine Kosmetik - ueberlappende Sauger liessen sich
nicht montieren, und einer ueber der Plattenkante haengt in der Luft.

Dazu die Eigenschaft, wegen der die Auswahl ueberhaupt existiert: die dichteste
Packung muss mehr Sauger unterbringen als das Quadratraster.
"""

from __future__ import annotations

import math

import pytest

from app.dto.vacuum import VacuumPlateSpec
from app.engines.vacuum import arrangements
from app.engines.vacuum.arrangements import ArrangementRequest
from app.engines.vacuum.layout import SuctionLayoutEngine

PLATES = [
    (750.0, 550.0, 44.0),    # Regelfall
    (750.0, 550.0, 61.0),    # grosser Sauger
    (300.0, 200.0, 44.0),    # kleine Platte
    (120.0, 90.0, 44.0),     # sehr kleine Platte
    (1950.0, 1450.0, 30.0),  # grosse Platte, kleiner Sauger
]


def _request(span_x: float, span_y: float, pitch: float) -> ArrangementRequest:
    return ArrangementRequest(
        span_x_mm=span_x, span_y_mm=span_y, pitch_mm=pitch,
        origin_x_mm=25.0, origin_y_mm=25.0,
    )


def _closest_pair_mm(centers) -> float:
    return min(
        math.dist(centers[i], centers[j])
        for i in range(len(centers))
        for j in range(i + 1, len(centers))
    )


# Grundeigenschaften ------------------------------------------------------------

def test_every_arrangement_is_registered_with_a_label():
    assert arrangements.available()
    for strategy_id in arrangements.available():
        assert arrangements.label_of(strategy_id) != strategy_id
        assert len(arrangements.description_of(strategy_id)) > 40


@pytest.mark.parametrize("strategy", arrangements.available())
@pytest.mark.parametrize("span_x,span_y,pitch", PLATES)
def test_minimum_spacing_is_never_violated(strategy, span_x, span_y, pitch):
    """Ueberlappende Sauger liessen sich nicht montieren."""
    layout = arrangements.generate(strategy, _request(span_x, span_y, pitch))
    if layout.count < 2:
        return
    closest = _closest_pair_mm(layout.centers)
    assert closest >= pitch - 1e-6, (
        strategy + ": kleinster Mittenabstand " + format(closest, ".2f")
        + " mm, gefordert " + format(pitch, ".2f") + " mm"
    )


@pytest.mark.parametrize("strategy", arrangements.available())
@pytest.mark.parametrize("span_x,span_y,pitch", PLATES)
def test_no_cup_leaves_the_usable_span(strategy, span_x, span_y, pitch):
    layout = arrangements.generate(strategy, _request(span_x, span_y, pitch))
    for x, y in layout.centers:
        assert 25.0 - 1e-6 <= x <= 25.0 + span_x + 1e-6
        assert 25.0 - 1e-6 <= y <= 25.0 + span_y + 1e-6


@pytest.mark.parametrize("strategy", arrangements.available())
def test_arrangements_are_reproducible(strategy):
    """Spezifikation 39."""
    request = _request(750.0, 550.0, 44.0)
    assert arrangements.generate(strategy, request).centers == \
           arrangements.generate(strategy, request).centers


def test_unknown_arrangement_is_a_clear_error():
    with pytest.raises(KeyError, match="Unbekanntes Saugermuster"):
        arrangements.generate("windrad", _request(750.0, 550.0, 44.0))


# Die einzelnen Muster ----------------------------------------------------------

def test_dense_packing_beats_the_square_grid():
    """Der Grund, warum es diese Auswahl gibt.

    Kreise gleicher Groesse lassen sich im Quadratraster bis pi/4 = 78,5 Prozent
    packen, versetzt bis pi/(2*sqrt(3)) = 90,7 Prozent. Auf derselben Platte
    passen damit rund fuenfzehn Prozent mehr Sauger.
    """
    request = _request(750.0, 550.0, 44.0)
    grid = arrangements.generate("grid_spread", request)
    dense = arrangements.generate("hexagonal", request)

    assert dense.count > grid.count
    assert dense.count / grid.count > 1.10


def test_dense_packing_uses_the_triangular_lattice():
    """Der Reihenabstand betraegt das sqrt(3)/2-fache des Rastermasses."""
    layout = arrangements.generate("hexagonal", _request(750.0, 550.0, 44.0))
    rows = sorted({round(y, 6) for _x, y in layout.centers})
    steps = [b - a for a, b in zip(rows, rows[1:])]
    expected = 44.0 * math.sqrt(3.0) / 2.0

    assert steps
    for step in steps:
        assert step == pytest.approx(expected, abs=1e-6)


def test_dense_rows_are_staggered():
    layout = arrangements.generate("hexagonal", _request(750.0, 550.0, 44.0))
    by_row: dict[float, list[float]] = {}
    for x, y in layout.centers:
        by_row.setdefault(round(y, 3), []).append(x)
    rows = sorted(by_row)
    first = min(by_row[rows[0]])
    second = min(by_row[rows[1]])
    assert abs(second - first) == pytest.approx(22.0, abs=0.01)


def test_spread_and_dense_grid_hold_the_same_count():
    """Beide Raster nehmen gleich viele Sauger auf - sie stehen nur anders."""
    request = _request(750.0, 550.0, 44.0)
    spread = arrangements.generate("grid_spread", request)
    dense = arrangements.generate("grid_dense", request)
    assert spread.count == dense.count

    spread_width = max(x for x, _y in spread.centers) - min(x for x, _y in spread.centers)
    dense_width = max(x for x, _y in dense.centers) - min(x for x, _y in dense.centers)
    assert dense_width <= spread_width + 1e-6


def test_perimeter_leaves_the_middle_empty():
    layout = arrangements.generate("perimeter", _request(750.0, 550.0, 44.0))
    grid = arrangements.generate("grid_spread", _request(750.0, 550.0, 44.0))
    assert 0 < layout.count < grid.count

    xs = sorted({round(x, 3) for x, _y in layout.centers})
    ys = sorted({round(y, 3) for _x, y in layout.centers})
    inner = [
        (x, y) for x, y in layout.centers
        if xs[0] < x < xs[-1] and ys[0] < y < ys[-1]
    ]
    assert not inner, "Die Mitte muss frei bleiben"


def test_over_packages_places_cups_only_on_cartons():
    """Ein Sauger ohne Karton darunter traegt nicht und zieht Fremdluft."""
    package = (200.0, 150.0, 300.0, 250.0)  # x, y, Laenge, Breite
    request = ArrangementRequest(
        span_x_mm=750.0, span_y_mm=550.0, pitch_mm=44.0,
        package_rects=(package,), origin_x_mm=25.0, origin_y_mm=25.0,
    )
    layout = arrangements.generate("over_packages", request)
    radius = 22.0

    assert layout.count > 0
    for x, y in layout.centers:
        assert package[0] <= x - radius and x + radius <= package[0] + package[2]
        assert package[1] <= y - radius and y + radius <= package[1] + package[3]

    without = arrangements.generate("hexagonal", request)
    assert layout.count < without.count


def test_over_packages_without_packages_falls_back():
    layout = arrangements.generate("over_packages", _request(750.0, 550.0, 44.0))
    assert layout.count > 0
    assert any("dichtest bestueckt" in note for note in layout.notes)


# Zusammenspiel mit der Verteilung ----------------------------------------------

@pytest.mark.parametrize("strategy", arrangements.available())
def test_layout_engine_honours_every_arrangement(strategy, settings):
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    cup = settings.get_suction_cup("spb2_30")
    layout = SuctionLayoutEngine().distribute(cup, plate, arrangement_id=strategy)

    assert layout.arrangement_id == strategy
    assert layout.count > 0

    # Kein Sauger darf ueber die Platte hinausragen - geprueft mit seinem
    # Aussenmass unter Vakuum, nicht mit dem Mittelpunkt.
    radius = cup.outer_diameter_mm / 2.0
    for placement in layout.placements:
        assert placement.center_x_mm - radius >= -1e-6
        assert placement.center_y_mm - radius >= -1e-6
        assert placement.center_x_mm + radius <= plate.length_mm + 1e-6
        assert placement.center_y_mm + radius <= plate.width_mm + 1e-6


@pytest.mark.parametrize("strategy", arrangements.available())
@pytest.mark.parametrize("wanted", [1, 4, 7, 24, 60])
def test_a_requested_count_is_met_by_every_arrangement(strategy, wanted, settings):
    """Die gewuenschte Zahl muss genau getroffen werden, nicht ungefaehr.

    Ausser sie uebersteigt, was das Muster aufnimmt - die Randverteilung hat auf
    dieser Platte nur 58 Plaetze. Dann gilt die Kapazitaet, und die Abweichung
    muss gemeldet sein.
    """
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    capacity = engine.capacity(cup, plate, strategy)

    layout = engine.distribute(cup, plate, wanted_count=wanted, arrangement_id=strategy)

    assert layout.count == min(wanted, capacity)
    if wanted > capacity:
        assert any("hoechstens" in note for note in layout.notes)


def test_a_reduced_count_still_covers_the_whole_plate(settings):
    """Ausgeduennt wird ueber das Rastermass, nicht durch Weglassen.

    Wuerde man einfach ueberzaehlige Sauger streichen, bliebe die obere
    Plattenhaelfte leer und die Platte kippte beim Anheben.
    """
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    layout = SuctionLayoutEngine().distribute(
        settings.get_suction_cup("spb2_30"), plate, wanted_count=24, arrangement_id="hexagonal",
    )
    ys = [p.center_y_mm for p in layout.placements]
    xs = [p.center_x_mm for p in layout.placements]
    assert max(ys) - min(ys) > plate.width_mm * 0.7
    assert max(xs) - min(xs) > plate.length_mm * 0.7


def test_capacity_depends_on_the_arrangement(settings):
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")

    grid = engine.capacity(cup, plate, "grid_spread")
    dense = engine.capacity(cup, plate, "hexagonal")
    edge = engine.capacity(cup, plate, "perimeter")

    assert dense > grid > edge > 0
