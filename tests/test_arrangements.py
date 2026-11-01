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

from app.vacuum.models import SCHMALZ_RASTER, VacuumPlateSpec
from app.vacuum import cup_patterns
from app.vacuum.cup_patterns import ArrangementRequest
from app.vacuum.layout import SuctionLayoutEngine

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


def _lattice_steps_mm(centers) -> tuple[float, float]:
    """Schrittweite innerhalb einer Reihe und von Reihe zu Reihe.

    Billiger als _closest_pair_mm und hier auch genauer: gesucht ist das
    Rastermass des Gitters, nicht der kleinste Abstand irgendwo. Vor allem aber
    laeuft diese Messung in n log n statt in n Quadrat - und das ist kein
    Geschmack, sondern eine Lehre. Mit einem Probewert von 0,5 mm Saugerbedarf
    entstehen bei durchgereichtem Rastermass rund 1,9 Millionen Positionen; die
    Paarsuche darueber kommt nicht zurueck. Eine Pruefung, die beim eingebauten
    Fehler haengt statt zu scheitern, nuetzt niemandem.
    """
    reihen: dict[float, list[float]] = {}
    for x, y in centers:
        reihen.setdefault(round(y, 6), []).append(x)

    hoehen = sorted(reihen)
    spalten = sorted(reihen[hoehen[0]])
    schritt_x = min((b - a for a, b in zip(spalten, spalten[1:])), default=0.0)
    schritt_y = min((b - a for a, b in zip(hoehen, hoehen[1:])), default=0.0)
    return schritt_x, schritt_y


# Grundeigenschaften ------------------------------------------------------------

def test_every_arrangement_is_registered_with_a_label():
    assert cup_patterns.available()
    for strategy_id in cup_patterns.available():
        assert cup_patterns.label_of(strategy_id) != strategy_id
        assert len(cup_patterns.description_of(strategy_id)) > 40


@pytest.mark.parametrize("strategy", cup_patterns.available())
@pytest.mark.parametrize("span_x,span_y,pitch", PLATES)
def test_minimum_spacing_is_never_violated(strategy, span_x, span_y, pitch):
    """Ueberlappende Sauger liessen sich nicht montieren."""
    layout = cup_patterns.generate(strategy, _request(span_x, span_y, pitch))
    if layout.count < 2:
        return
    closest = _closest_pair_mm(layout.centers)
    assert closest >= pitch - 1e-6, (
        strategy + ": kleinster Mittenabstand " + format(closest, ".2f")
        + " mm, gefordert " + format(pitch, ".2f") + " mm"
    )


@pytest.mark.parametrize("strategy", cup_patterns.available())
@pytest.mark.parametrize("span_x,span_y,pitch", PLATES)
def test_no_cup_leaves_the_usable_span(strategy, span_x, span_y, pitch):
    layout = cup_patterns.generate(strategy, _request(span_x, span_y, pitch))
    for x, y in layout.centers:
        assert 25.0 - 1e-6 <= x <= 25.0 + span_x + 1e-6
        assert 25.0 - 1e-6 <= y <= 25.0 + span_y + 1e-6


@pytest.mark.parametrize("strategy", cup_patterns.available())
def test_arrangements_are_reproducible(strategy):
    """Spezifikation 39."""
    request = _request(750.0, 550.0, 44.0)
    assert cup_patterns.generate(strategy, request).centers == \
           cup_patterns.generate(strategy, request).centers


def test_unknown_arrangement_is_a_clear_error():
    with pytest.raises(KeyError, match="Unbekanntes Saugermuster"):
        cup_patterns.generate("windrad", _request(750.0, 550.0, 44.0))


# Die einzelnen Muster ----------------------------------------------------------

def test_dense_packing_beats_the_square_grid():
    """Der Grund, warum es diese Auswahl gibt.

    Kreise gleicher Groesse lassen sich im Quadratraster bis pi/4 = 78,5 Prozent
    packen, versetzt bis pi/(2*sqrt(3)) = 90,7 Prozent. Auf derselben Platte
    passen damit rund fuenfzehn Prozent mehr Sauger.
    """
    request = _request(750.0, 550.0, 44.0)
    grid = cup_patterns.generate("grid_spread", request)
    dense = cup_patterns.generate("hexagonal", request)

    assert dense.count > grid.count
    assert dense.count / grid.count > 1.10


def test_dense_packing_uses_the_triangular_lattice():
    """Der Reihenabstand betraegt das sqrt(3)/2-fache des Rastermasses."""
    layout = cup_patterns.generate("hexagonal", _request(750.0, 550.0, 44.0))
    rows = sorted({round(y, 6) for _x, y in layout.centers})
    steps = [b - a for a, b in zip(rows, rows[1:])]
    expected = 44.0 * math.sqrt(3.0) / 2.0

    assert steps
    for step in steps:
        assert step == pytest.approx(expected, abs=1e-6)


def test_dense_rows_are_staggered():
    layout = cup_patterns.generate("hexagonal", _request(750.0, 550.0, 44.0))
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
    spread = cup_patterns.generate("grid_spread", request)
    dense = cup_patterns.generate("grid_dense", request)
    assert spread.count == dense.count

    spread_width = max(x for x, _y in spread.centers) - min(x for x, _y in spread.centers)
    dense_width = max(x for x, _y in dense.centers) - min(x for x, _y in dense.centers)
    assert dense_width <= spread_width + 1e-6


def test_perimeter_leaves_the_middle_empty():
    layout = cup_patterns.generate("perimeter", _request(750.0, 550.0, 44.0))
    grid = cup_patterns.generate("grid_spread", _request(750.0, 550.0, 44.0))
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
    layout = cup_patterns.generate("over_packages", request)
    radius = 22.0

    assert layout.count > 0
    for x, y in layout.centers:
        assert package[0] <= x - radius and x + radius <= package[0] + package[2]
        assert package[1] <= y - radius and y + radius <= package[1] + package[3]

    without = cup_patterns.generate("hexagonal", request)
    assert layout.count < without.count


def test_over_packages_without_packages_falls_back():
    layout = cup_patterns.generate("over_packages", _request(750.0, 550.0, 44.0))
    assert layout.count > 0
    assert any("dichtest bestueckt" in note for note in layout.notes)


# Das vorgegebene Rastermass -----------------------------------------------------
#
# Schmalz kennzeichnet die Lagengreifer ZLW mit 20T, 30T und 45T; die Zahl ist
# der Mittenabstand der Saugstellen, die Anordnung nennt der Hersteller
# "Dreieck". Das Dreiecksgitter rechnet hexagonal() schon - ein eigenes Muster
# dafuer waere eine Dublette gewesen (siehe
# test_a_build_form_is_the_same_thing_as_the_dense_packing).
#
# Vorgegeben wird deshalb nur das RASTERMASS, an der Platte. Was diese Tests
# festhalten: es wird nicht angetastet, auch nicht, wenn der Sauger nicht
# hineinpasst - und dass es dann ueberlappt, wird gesagt.


def test_the_build_forms_are_the_three_schmalz_rasters():
    assert SCHMALZ_RASTER == (("20T", 20.0), ("30T", 30.0), ("45T", 45.0))
    assert VacuumPlateSpec(800.0, 600.0, raster_pitch_mm=30.0).raster_label == "30T"
    assert VacuumPlateSpec(800.0, 600.0, raster_pitch_mm=36.0).raster_label == ""
    assert VacuumPlateSpec(800.0, 600.0).raster_label == ""


@pytest.mark.parametrize("pitch", [20.0, 30.0, 45.0, 36.0])
def test_a_given_raster_pitch_is_used_exactly(pitch, settings):
    """30T heisst 30,0 mm Mittenabstand - nicht ungefaehr und nicht gerundet.

    Das freie Mass 36,0 steht mit in der Liste: es ist keine Bauform, muss aber
    genauso genau getroffen werden.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_20")
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=0.0, raster_pitch_mm=pitch)

    assert engine.pitch_mm(cup, plate) == pytest.approx(pitch, abs=1e-9)

    layout = engine.distribute(cup, plate, arrangement_id="hexagonal")
    mitten = tuple((p.center_x_mm, p.center_y_mm) for p in layout.placements)
    assert _closest_pair_mm(mitten) == pytest.approx(pitch, abs=1e-6)


@pytest.mark.parametrize("cup_id", ["spb1_10", "spb2_25", "spb2_30", "spb2_50"])
def test_a_given_raster_pitch_never_follows_the_cup(cup_id, settings):
    """Der Sauger bewegt das vorgegebene Rastermass nicht - in keine Richtung.

    Nach oben nicht: SPB2 50 braeuchte 55,5 mm und bekommt trotzdem 30. Nach
    unten auch nicht: SPB1 10 braeuchte nur 11,3 mm und bekommt trotzdem 30.
    Beides zusammen ist die Zusage, die eine Bauform ausmacht - ohne die eine
    Richtung waere "30T" in der Anzeige eine Behauptung ohne Deckung.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup(cup_id)
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=0.0, raster_pitch_mm=30.0)

    assert engine.pitch_mm(cup, plate) == pytest.approx(30.0, abs=1e-9)
    assert engine.clearance_mm(cup, plate) == pytest.approx(
        30.0 - cup.outer_diameter_mm, abs=1e-9
    )


def test_a_build_form_is_the_same_thing_as_the_dense_packing(settings):
    """Warum es kein eigenes Schmalz-Muster gibt.

    SPB2 25 ist 28,0 mm breit. Die dichteste Packung mit 2 mm lichtem Abstand
    und die Bauform 30T ergeben beide 30,0 mm Rastermass - und damit Sauger fuer
    Sauger dieselbe Platte. Ein zweiter Registryeintrag haette genau dasselbe
    gerechnet.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_25")
    gerechnet = VacuumPlateSpec(850.0, 650.0, edge_margin_mm=0.0, min_spacing_mm=2.0)
    bauform = VacuumPlateSpec(850.0, 650.0, edge_margin_mm=0.0, raster_pitch_mm=30.0)

    assert engine.pitch_mm(cup, gerechnet) == engine.pitch_mm(cup, bauform) == 30.0

    a = engine.distribute(cup, gerechnet, arrangement_id="hexagonal")
    b = engine.distribute(cup, bauform, arrangement_id="hexagonal")
    assert a.count == b.count > 0
    assert [(p.center_x_mm, p.center_y_mm) for p in a.placements] == \
           [(p.center_x_mm, p.center_y_mm) for p in b.placements]


def test_an_overlapping_raster_is_drawn_and_reported(settings):
    """Ueberlappung ist erlaubt - verschwiegen wird sie nicht.

    SPB2 30 ist 34,0 mm breit und passt nicht in 20T. Frueher lehnte das
    Programm die Kombination ab; jetzt zeichnet es sie, damit sich das Raster
    ansehen laesst, und sagt im selben Atemzug, dass die Haltekraft dadurch zu
    hoch ist.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=0.0, raster_pitch_mm=20.0)

    assert engine.clearance_mm(cup, plate) == pytest.approx(-14.0, abs=1e-9)

    layout = engine.distribute(cup, plate, arrangement_id="hexagonal")
    assert layout.count > 0, "gezeichnet werden muss trotzdem"

    text = " ".join(layout.notes)
    assert "20 mm" in text and "34 mm" in text, text
    assert "14.0 mm" in text, text
    assert "zu hoch" in text, "Der Satz zur Haltekraft fehlt: " + text


def test_a_raster_that_fits_says_nothing_about_overlap(settings):
    """Gegenstueck: keine Warnung, wo nichts ueberlappt."""
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=0.0, raster_pitch_mm=45.0)

    assert engine.overlap_note(cup, plate) == ""
    assert not any("ueberlappen" in note for note in
                   engine.distribute(cup, plate, arrangement_id="hexagonal").notes)


def test_a_device_the_manufacturer_really_sells_is_buildable(settings):
    """Gegenprobe an der Quelle: ZLW FL 850x650 SE SPB2 40 45T.

    Das Geraet gibt es, also muss die Kombination aufgehen. Sie tut es genau
    dann, wenn die 45 der MITTENabstand ist: SPB2 40 ist unter Vakuum 44,5 mm
    breit, es bleiben 0,5 mm Luft. Als lichter Abstand gelesen waere der
    Mittenabstand 89,5 mm, und es gaebe dieses Geraet nicht.

    Dieser Test ist der Grund, warum der T-Wert unveraendert als Rastermass
    durchgereicht wird.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_40")
    assert cup.outer_diameter_mm == 44.5

    plate = VacuumPlateSpec(850.0, 650.0, edge_margin_mm=0.0, raster_pitch_mm=45.0)
    assert engine.clearance_mm(cup, plate) == pytest.approx(0.5, abs=1e-9)
    assert engine.overlap_note(cup, plate) == ""

    layout = engine.distribute(cup, plate, arrangement_id="hexagonal")
    assert layout.count > 0
    assert layout.pitch_x_mm == pytest.approx(45.0, abs=1e-6)


def test_a_given_raster_is_thinned_by_leaving_places_empty(settings):
    """Eine kleinere Stueckzahl darf das vorgegebene Rastermass nicht aufweiten.

    Ohne Vorgabe wird genau das getan (siehe _thin_to): das Rastermass waechst,
    bis die Zahl stimmt, und die Sauger bleiben ueber die ganze Platte verteilt.
    Mit Vorgabe ginge dabei die Bauform verloren - aus 45T wuerde ein Raster,
    das es nicht gibt. Also bleibt das Raster stehen, und Plaetze bleiben leer.
    """
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, raster_pitch_mm=45.0)
    capacity = engine.capacity(cup, plate, "hexagonal")
    assert capacity > 10

    wanted = capacity // 2
    layout = engine.distribute(cup, plate, wanted_count=wanted, arrangement_id="hexagonal")

    assert layout.count == wanted
    assert layout.pitch_x_mm == pytest.approx(45.0, abs=1e-6)
    assert _closest_pair_mm(
        tuple((p.center_x_mm, p.center_y_mm) for p in layout.placements)
    ) == pytest.approx(45.0, abs=1e-6)
    assert any("nicht aufgeweitet" in note for note in layout.notes), layout.notes


def test_without_a_given_pitch_the_cup_decides(settings):
    """Die Grundstellung bleibt, was sie war: Aussenmass plus lichter Abstand."""
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=0.0, min_spacing_mm=6.0)

    assert plate.raster_pitch_mm == 0.0
    assert engine.pitch_mm(cup, plate) == pytest.approx(40.0, abs=1e-9)
    assert engine.clearance_mm(cup, plate) == pytest.approx(6.0, abs=1e-9)


# Zusammenspiel mit der Verteilung ----------------------------------------------

@pytest.mark.parametrize("strategy", cup_patterns.available())
def test_layout_engine_honours_every_arrangement(strategy, settings):
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    cup = settings.get_suction_cup("spb2_30")
    layout = SuctionLayoutEngine().distribute(cup, plate, arrangement_id=strategy)

    assert layout.arrangement_id == strategy
    if layout.count == 0:
        # Ein festes Raster kann fuer diesen Sauger zu eng sein - SPB2 30
        # braucht mit 10 mm Mindestabstand 44 mm, 20T und 30T geben weniger.
        # Das ist erlaubt. Stillschweigend leer zu bleiben ist es nicht.
        assert layout.notes, strategy + ": leere Platte ohne ein Wort dazu"
        return

    # Kein Sauger darf ueber die Platte hinausragen - geprueft mit seinem
    # Aussenmass unter Vakuum, nicht mit dem Mittelpunkt.
    radius = cup.outer_diameter_mm / 2.0
    for placement in layout.placements:
        assert placement.center_x_mm - radius >= -1e-6
        assert placement.center_y_mm - radius >= -1e-6
        assert placement.center_x_mm + radius <= plate.length_mm + 1e-6
        assert placement.center_y_mm + radius <= plate.width_mm + 1e-6


@pytest.mark.parametrize("strategy", cup_patterns.available())
@pytest.mark.parametrize("wanted", [1, 4, 7, 24, 60])
def test_a_requested_count_is_met_by_every_arrangement(strategy, wanted, settings):
    """Die gewuenschte Zahl muss genau getroffen werden, nicht ungefaehr.

    Ausser sie uebersteigt, was das Muster aufnimmt - die Randverteilung hat auf
    dieser Platte nur 58 Plaetze. Dann gilt die Kapazitaet, und die Abweichung
    muss gemeldet sein.

    Null Plaetze ist dabei ein eigener Fall: die festen Raster 20T und 30T sind
    mit diesem Sauger gar nicht baubar. Dann gibt es keine Obergrenze, die man
    nennen koennte - gefordert ist nur, dass ueberhaupt etwas dasteht.
    """
    plate = VacuumPlateSpec(800.0, 600.0, edge_margin_mm=25.0, min_spacing_mm=10.0)
    engine = SuctionLayoutEngine()
    cup = settings.get_suction_cup("spb2_30")
    capacity = engine.capacity(cup, plate, strategy)

    layout = engine.distribute(cup, plate, wanted_count=wanted, arrangement_id=strategy)

    assert layout.count == min(wanted, capacity)
    if layout.count < wanted:
        assert layout.notes, (
            strategy + ": " + str(layout.count) + " von " + str(wanted)
            + " Saugern gesetzt, ohne einen Hinweis darauf"
        )
    if 0 < capacity < wanted:
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
