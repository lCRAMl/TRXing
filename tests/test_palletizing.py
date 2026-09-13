"""Tests der Palettier-Engine.

Der Schwerpunkt liegt auf den Eigenschaften, die ein Palettierplan haben muss,
damit man ihn benutzen kann: keine Ueberschneidungen, nichts ueber der
Palettenkante, Grenzwerte eingehalten, und bei gleicher Eingabe dasselbe
Ergebnis.
"""

from __future__ import annotations

import pytest

from app.dto.package import Orientation, PackageSpec
from app.dto.pallet import LimitingFactor, PatternSpec, ZMode
from app.engines.geometry.shapes import any_overlap
from app.engines.palletizing import loads
from app.engines.palletizing.optimizer import PalletOptimizer, PalletizingError, build_constraints
from app.engines.patterns import PatternRequest, available_strategies, generate

ALL_PATTERNS = [
    "auto", "aligned", "column", "rotated", "brick", "cross", "alternating",
    "checkerboard", "pinwheel", "spiral", "perimeter", "ring", "max_count",
]


@pytest.fixture
def optimizer():
    return PalletOptimizer()


def _rects(result) -> list[tuple[float, float, float, float]]:
    return [(p.x_mm, p.y_mm, p.length_mm, p.width_mm) for p in result.layers[0].placements]


# Musterschicht ----------------------------------------------------------------

def test_every_configured_strategy_is_registered(settings):
    """Ein Muster in der Konfiguration ohne Strategie im Code waere ein Tab,
    dessen Auswahl ins Leere laeuft."""
    known = set(available_strategies())
    missing = [p.id + " -> " + p.strategy for p in settings.get_patterns() if p.strategy not in known]
    assert not missing, "Muster ohne Strategie: " + ", ".join(missing)


@pytest.mark.parametrize("strategy", sorted(available_strategies()))
def test_no_strategy_produces_overlaps(strategy):
    request = PatternRequest(1200.0, 800.0, 400.0, 300.0)
    layout = generate(strategy, request)
    rects = [(f.x_mm, f.y_mm, f.length_mm, f.width_mm) for f in layout.footprints]
    assert not any_overlap(rects), "Strategie " + strategy + " legt Pakete uebereinander"


@pytest.mark.parametrize("strategy", sorted(available_strategies()))
def test_no_strategy_leaves_the_bounds(strategy):
    request = PatternRequest(1200.0, 800.0, 400.0, 300.0)
    layout = generate(strategy, request)
    for f in layout.footprints:
        assert f.x_mm >= -1e-6 and f.y_mm >= -1e-6
        assert f.x_mm + f.length_mm <= 1200.0 + 1e-6
        assert f.y_mm + f.width_mm <= 800.0 + 1e-6


@pytest.mark.parametrize("strategy", sorted(available_strategies()))
def test_strategies_are_reproducible(strategy):
    """Spezifikation 39: identische Eingabe, identisches Ergebnis."""
    request = PatternRequest(1200.0, 800.0, 380.0, 265.0, options={"use_solver": False})
    assert generate(strategy, request).footprints == generate(strategy, request).footprints


def test_uniform_grid_fills_an_exact_fit():
    layout = generate("uniform_grid", PatternRequest(1200.0, 800.0, 400.0, 400.0))
    assert layout.count == 6
    assert layout.used_area_mm2 == pytest.approx(1200.0 * 800.0)


def test_rotation_is_used_when_it_fits_more():
    """400x300 quer liefert 8 statt 6 - der Packer muss die Drehung finden."""
    layout = generate("uniform_grid", PatternRequest(1200.0, 800.0, 400.0, 300.0))
    assert layout.count == 8
    assert all(f.rotated for f in layout.footprints)


def test_gap_is_respected_between_neighbours():
    layout = generate("uniform_grid", PatternRequest(1200.0, 800.0, 400.0, 300.0, gap_mm=20.0))
    by_row: dict[float, list] = {}
    for f in layout.footprints:
        by_row.setdefault(round(f.y_mm, 3), []).append(f)
    for row in by_row.values():
        row.sort(key=lambda f: f.x_mm)
        for left, right in zip(row, row[1:]):
            assert right.x_mm - (left.x_mm + left.length_mm) >= 20.0 - 1e-6


def test_running_bond_offsets_every_other_row():
    layout = generate("running_bond", PatternRequest(1200.0, 800.0, 400.0, 200.0))
    rows = sorted({round(f.y_mm, 3) for f in layout.footprints})
    assert len(rows) >= 2
    first = sorted(f.x_mm for f in layout.footprints if abs(f.y_mm - rows[0]) < 1e-6)
    second = sorted(f.x_mm for f in layout.footprints if abs(f.y_mm - rows[1]) < 1e-6)
    assert first != second, "Der Laeuferverband muss die Reihen gegeneinander versetzen"


def test_ring_leaves_the_core_empty():
    layout = generate("ring", PatternRequest(1500.0, 1500.0, 200.0, 200.0))
    columns = sorted({round(f.x_mm, 3) for f in layout.footprints})
    rows = sorted({round(f.y_mm, 3) for f in layout.footprints})
    assert len(columns) >= 3 and len(rows) >= 3
    inner = [f for f in layout.footprints
             if columns[0] < f.x_mm < columns[-1] and rows[0] < f.y_mm < rows[-1]]
    assert not inner, "Der Ringstapel muss den Kern frei lassen"


def test_approximation_is_declared(settings):
    """Spezifikation 25: jede Naeherung muss erkennbar sein."""
    layout = generate("checkerboard", PatternRequest(1200.0, 800.0, 400.0, 300.0))
    assert layout.notes, "Der bandweise Wechsel muss gemeldet werden"
    square = generate("checkerboard", PatternRequest(1200.0, 800.0, 300.0, 300.0))
    assert not square.notes, "Bei quadratischem Paket wechselt es feldweise - nichts zu melden"


def test_square_package_keeps_the_real_checkerboard():
    """Bei quadratischem Paket bleibt der feldweise Wechsel erhalten."""
    layout = generate("checkerboard", PatternRequest(1200.0, 900.0, 300.0, 300.0))
    by_row: dict[float, list] = {}
    for footprint in layout.footprints:
        by_row.setdefault(round(footprint.y_mm, 3), []).append(footprint)

    for row in by_row.values():
        row.sort(key=lambda f: f.x_mm)
        flags = [f.rotated for f in row]
        assert flags == [i % 2 == (1 if flags[0] is False else 0) for i in range(len(flags))] or \
               all(a != b for a, b in zip(flags, flags[1:])), \
               "Innerhalb einer Reihe muss die Ausrichtung feldweise wechseln"


def _enclosed_void_mm2(footprints, step: float = 5.0) -> float:
    """Freie Flaeche, die ringsum von Paketen eingeschlossen ist.

    Rasterabtastung mit anschliessendem Flutfuellen vom Rand her: was danach
    noch frei ist, ist von allen Seiten umschlossen. Eine freie Flaeche am
    Aussenrand zaehlt ausdruecklich nicht - sie laesst sich bei keiner
    Paketgroesse vermeiden.
    """
    from collections import deque

    if not footprints:
        return 0.0
    min_x = min(f.x_mm for f in footprints)
    min_y = min(f.y_mm for f in footprints)
    max_x = max(f.x_mm + f.length_mm for f in footprints)
    max_y = max(f.y_mm + f.width_mm for f in footprints)

    columns = int((max_x - min_x) / step) + 1
    rows = int((max_y - min_y) / step) + 1
    free = [[True] * columns for _ in range(rows)]

    for f in footprints:
        c0 = max(0, int((f.x_mm - min_x) / step))
        c1 = min(columns - 1, int((f.x_mm + f.length_mm - min_x) / step))
        r0 = max(0, int((f.y_mm - min_y) / step))
        r1 = min(rows - 1, int((f.y_mm + f.width_mm - min_y) / step))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                free[r][c] = False

    queue = deque()
    for r in range(rows):
        for c in (0, columns - 1):
            if free[r][c]:
                free[r][c] = False
                queue.append((r, c))
    for c in range(columns):
        for r in (0, rows - 1):
            if free[r][c]:
                free[r][c] = False
                queue.append((r, c))
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < columns and free[nr][nc]:
                free[nr][nc] = False
                queue.append((nr, nc))

    return sum(row.count(True) for row in free) * step * step


@pytest.mark.parametrize(
    "item_length,item_width",
    [(400.0, 300.0), (350.0, 250.0), (300.0, 300.0), (200.0, 150.0), (600.0, 200.0), (250.0, 240.0)],
)
@pytest.mark.parametrize(
    "strategy",
    ["checkerboard", "pinwheel", "spiral", "perimeter", "uniform_grid", "guillotine_mix", "running_bond"],
)
def test_no_pattern_leaves_gaps_between_packages(strategy, item_length, item_width):
    """Die Kernanforderung an die Muster: Paket an Paket, kein Hohlraum.

    Eine Luecke mitten in der Ladung ist kein Schoenheitsfehler - die Pakete
    verrutschen darin beim Transport. Geprueft wird auf eingeschlossene
    Hohlraeume; ein freier Streifen am Aussenrand bleibt erlaubt, weil er sich
    bei keiner Paketgroesse vermeiden laesst.

    Der Ringstapel ist ausgenommen: sein freier Kern ist die Definition des
    Musters.
    """
    layout = generate(strategy, PatternRequest(1200.0, 800.0, item_length, item_width))
    void = _enclosed_void_mm2(layout.footprints)
    assert void == 0.0, (
        strategy + " bei " + format(item_length, ".0f") + "x" + format(item_width, ".0f")
        + " mm laesst " + format(void, ".0f") + " mm2 eingeschlossenen Hohlraum"
    )


def test_ring_is_the_documented_exception():
    """Der Ringstapel darf als einziges Muster einen freien Kern haben."""
    layout = generate("ring", PatternRequest(1500.0, 1500.0, 200.0, 200.0))
    assert _enclosed_void_mm2(layout.footprints) > 0.0
    assert any("Kern" in note for note in layout.notes), "Der freie Kern muss benannt sein"


def test_max_count_is_at_least_as_good_as_the_simple_grid():
    request = PatternRequest(1200.0, 800.0, 350.0, 250.0)
    assert generate("max_count", request).count >= generate("uniform_grid", request).count


# Optimierer -------------------------------------------------------------------

@pytest.mark.parametrize("pattern_id", ALL_PATTERNS)
def test_every_pattern_produces_a_usable_plan(optimizer, settings, euro_pallet, package, pattern_id):
    pattern = settings.get_pattern(pattern_id)
    result = optimizer.optimize(package, euro_pallet, pattern, build_constraints(euro_pallet, package))

    assert result.total_count > 0
    assert result.layer_count > 0
    assert not any_overlap(_rects(result))
    assert result.pattern_id == pattern_id


def test_package_stays_on_the_pallet(optimizer, settings, euro_pallet, package):
    result = optimizer.optimize(
        package, euro_pallet, settings.get_pattern("auto"), build_constraints(euro_pallet, package)
    )
    for layer in result.layers:
        for p in layer.placements:
            assert p.x_mm >= -1e-6 and p.y_mm >= -1e-6
            assert p.right_mm <= euro_pallet.usable_length_mm + 1e-6
            assert p.top_mm <= euro_pallet.usable_width_mm + 1e-6


def test_height_limit_is_respected(optimizer, settings, euro_pallet, package):
    constraints = build_constraints(euro_pallet, package, max_height_mm=800.0)
    result = optimizer.optimize(package, euro_pallet, settings.get_pattern("aligned"), constraints)

    assert result.layer_count == 4  # 800 / 200
    assert result.total_load_height_mm <= 800.0
    assert result.limiting_factor is LimitingFactor.HEIGHT


def test_pallet_load_limit_is_respected(optimizer, settings, euro_pallet):
    heavy = PackageSpec(400.0, 300.0, 200.0, 40.0, max_stack_load_kg=5000.0)
    constraints = build_constraints(euro_pallet, heavy)
    result = optimizer.optimize(heavy, euro_pallet, settings.get_pattern("aligned"), constraints)

    assert result.total_weight_kg <= euro_pallet.max_load_kg
    assert result.limiting_factor is LimitingFactor.PALLET_LOAD


def test_package_stack_load_limits_the_height(optimizer, settings, euro_pallet):
    """Spezifikation 12.3: die Belastbarkeit des Pakets begrenzt den Stapel."""
    fragile = PackageSpec(400.0, 300.0, 200.0, 5.0, max_stack_load_kg=15.0)
    result = optimizer.optimize(
        fragile, euro_pallet, settings.get_pattern("column"), build_constraints(euro_pallet, fragile)
    )

    # 15 kg zulaessig, 5 kg je Paket: das unterste traegt drei Pakete = 15 kg.
    assert result.layer_count == 4
    assert result.limiting_factor is LimitingFactor.PACKAGE_LOAD
    assert result.load.critical_count == 0


def test_no_stack_load_means_no_load_check(optimizer, settings, euro_pallet):
    unlimited = PackageSpec(400.0, 300.0, 200.0, 5.0, max_stack_load_kg=0.0)
    result = optimizer.optimize(
        unlimited, euro_pallet, settings.get_pattern("aligned"), build_constraints(euro_pallet, unlimited)
    )
    assert result.load.checked is False
    assert result.limiting_factor is LimitingFactor.HEIGHT


def test_desired_count_trims_the_stack(optimizer, settings, euro_pallet, package):
    constraints = build_constraints(euro_pallet, package, desired_count=20)
    result = optimizer.optimize(package, euro_pallet, settings.get_pattern("aligned"), constraints)

    assert result.total_count == 20
    assert result.limiting_factor is LimitingFactor.DESIRED_COUNT


def test_unreachable_desired_count_warns(optimizer, settings, euro_pallet, package):
    constraints = build_constraints(euro_pallet, package, desired_count=100000)
    result = optimizer.optimize(package, euro_pallet, settings.get_pattern("aligned"), constraints)

    assert result.total_count < 100000
    assert any("Gewuenscht waren" in w for w in result.warnings)


def test_oversized_package_is_rejected_with_a_clear_message(optimizer, settings, euro_pallet):
    huge = PackageSpec(2000.0, 2000.0, 200.0, 5.0)
    with pytest.raises(PalletizingError, match="passt in keiner"):
        optimizer.optimize(huge, euro_pallet, settings.get_pattern("auto"), build_constraints(euro_pallet, huge))


def test_package_taller_than_the_limit_is_rejected(optimizer, settings, euro_pallet):
    tall = PackageSpec(400.0, 300.0, 900.0, 5.0)
    constraints = build_constraints(euro_pallet, tall, max_height_mm=500.0)
    with pytest.raises(PalletizingError, match="keine vollstaendige Lage"):
        optimizer.optimize(tall, euro_pallet, settings.get_pattern("auto"), constraints)


def test_tipping_is_off_by_default(optimizer, settings, euro_pallet):
    flat = PackageSpec(600.0, 400.0, 100.0, 5.0)
    result = optimizer.optimize(
        flat, euro_pallet, settings.get_pattern("auto"), build_constraints(euro_pallet, flat)
    )
    assert all(p.orientation is Orientation.UPRIGHT for layer in result.layers for p in layer.placements)


def test_tipping_can_improve_the_count(optimizer, settings, euro_pallet):
    """Ein flaches, breites Paket passt hochkant oefter auf die Palette."""
    flat = PackageSpec(700.0, 500.0, 150.0, 4.0, allow_tipping=True)
    upright_only = PackageSpec(700.0, 500.0, 150.0, 4.0, allow_tipping=False)
    pattern = settings.get_pattern("aligned")

    tipped = optimizer.optimize(flat, euro_pallet, pattern, build_constraints(euro_pallet, flat))
    plain = optimizer.optimize(upright_only, euro_pallet, pattern, build_constraints(euro_pallet, upright_only))

    assert tipped.total_count >= plain.total_count


def test_z_modes_differ(optimizer, settings, euro_pallet, package):
    """Saeule und Verband duerfen nicht dieselbe Anordnung liefern."""
    base = settings.get_pattern("aligned")
    identical = PatternSpec(id="t_id", name="t", strategy="uniform_grid", z_mode=ZMode.IDENTICAL)
    mirrored = PatternSpec(id="t_mi", name="t", strategy="running_bond", z_mode=ZMode.MIRROR)

    a = optimizer.optimize(package, euro_pallet, identical, build_constraints(euro_pallet, package))
    b = optimizer.optimize(package, euro_pallet, mirrored, build_constraints(euro_pallet, package))

    assert a.layer_count > 1 and b.layer_count > 1
    layer_a = [(p.x_mm, p.y_mm) for p in a.layers[1].placements]
    base_a = [(p.x_mm, p.y_mm) for p in a.layers[0].placements]
    assert layer_a == base_a, "Bei IDENTICAL muss die zweite Lage deckungsgleich sein"

    layer_b = sorted((round(p.x_mm, 3), round(p.y_mm, 3)) for p in b.layers[1].placements)
    base_b = sorted((round(p.x_mm, 3), round(p.y_mm, 3)) for p in b.layers[0].placements)
    assert layer_b != base_b, "Bei MIRROR muss die zweite Lage versetzt liegen"


def test_result_numbers_are_consistent(optimizer, settings, euro_pallet, package):
    result = optimizer.optimize(
        package, euro_pallet, settings.get_pattern("aligned"), build_constraints(euro_pallet, package)
    )
    assert result.total_count == sum(layer.count for layer in result.layers)
    assert result.total_weight_kg == pytest.approx(result.total_count * package.weight_kg)
    assert result.total_load_height_mm == pytest.approx(result.layer_count * package.height_mm)
    assert result.total_height_mm == pytest.approx(result.total_load_height_mm + euro_pallet.deck_height_mm)
    assert 0.0 <= result.footprint_utilization_ratio <= 1.0
    assert 0.0 <= result.volume_utilization_ratio <= 1.0


def test_package_indices_are_unique(optimizer, settings, euro_pallet, package):
    result = optimizer.optimize(
        package, euro_pallet, settings.get_pattern("brick"), build_constraints(euro_pallet, package)
    )
    indices = [p.package_index for layer in result.layers for p in layer.placements]
    assert len(indices) == len(set(indices))


def test_result_is_reproducible(optimizer, settings, euro_pallet, package):
    pattern = settings.get_pattern("auto")
    constraints = build_constraints(euro_pallet, package)
    first = optimizer.optimize(package, euro_pallet, pattern, constraints)
    second = optimizer.optimize(package, euro_pallet, pattern, constraints)

    assert first.total_count == second.total_count
    assert [(p.x_mm, p.y_mm, p.z_mm, p.rotated) for l in first.layers for p in l.placements] == \
           [(p.x_mm, p.y_mm, p.z_mm, p.rotated) for l in second.layers for p in l.placements]


def test_overhang_allows_more_packages(optimizer, settings, package):
    plain = settings.get_pallet("euro_1200x800")
    wide = settings.get_pallet("euro_overhang_1200x800")
    big = PackageSpec(410.0, 400.0, 200.0, 5.0)
    pattern = settings.get_pattern("aligned")

    without = optimizer.optimize(big, plain, pattern, build_constraints(plain, big))
    with_overhang = optimizer.optimize(big, wide, pattern, build_constraints(wide, big))

    assert with_overhang.per_layer_count > without.per_layer_count


def test_trace_records_the_path(optimizer, settings, euro_pallet, package):
    """Spezifikation 41: der Rechenweg muss nachvollziehbar sein."""
    result = optimizer.optimize(
        package, euro_pallet, settings.get_pattern("auto"),
        build_constraints(euro_pallet, package), request_id=17, state_revision=4,
    )
    names = [step.name for step in result.trace.steps]
    assert names == ["eingabe", "ausrichtungen", "musterkandidaten", "bester_kandidat", "lastverteilung"]
    assert result.trace.request_id == 17
    assert result.meta.state_revision == 4
    assert result.meta.algorithm_version


def test_cancellation_stops_the_run(optimizer, settings, euro_pallet, package):
    from app.core.cancellation import CancellationToken, CancelledError

    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        optimizer.optimize(
            package, euro_pallet, settings.get_pattern("auto"),
            build_constraints(euro_pallet, package), token=token,
        )


# Lastkaskade ------------------------------------------------------------------

def test_column_stack_loads_match_the_simple_rule(optimizer, settings, euro_pallet):
    """Im Saeulenstapel muss die Kaskade die Regel aus 12.3 reproduzieren."""
    box = PackageSpec(400.0, 400.0, 200.0, 10.0, max_stack_load_kg=1000.0)
    constraints = build_constraints(euro_pallet, box, max_height_mm=800.0)
    result = optimizer.optimize(box, euro_pallet, settings.get_pattern("column"), constraints)

    assert result.layer_count == 4
    by_layer: dict[int, set[float]] = {}
    for entry in result.load.per_package:
        by_layer.setdefault(entry.layer_index, set()).add(round(entry.supported_weight_kg, 6))

    assert by_layer[3] == {0.0}    # oberste Lage traegt nichts
    assert by_layer[2] == {10.0}   # ein Paket darueber
    assert by_layer[1] == {20.0}   # zwei Pakete darueber
    assert by_layer[0] == {30.0}   # drei Pakete darueber


def test_max_layers_by_stack_load_is_the_column_rule():
    assert loads.max_layers_by_stack_load(5.0, 15.0) == 4
    assert loads.max_layers_by_stack_load(5.0, 0.0) == 0    # keine Begrenzung
    assert loads.max_layers_by_stack_load(0.0, 15.0) == 0


def test_load_exactly_at_the_limit_is_not_critical(optimizer, settings, euro_pallet):
    """Die zulaessige Stapellast darf erreicht werden - sie ist die Obergrenze."""
    box = PackageSpec(400.0, 400.0, 200.0, 10.0, max_stack_load_kg=30.0)
    result = optimizer.optimize(
        box, euro_pallet, settings.get_pattern("column"), build_constraints(euro_pallet, box)
    )
    assert result.load.max_load_pct == pytest.approx(100.0)
    assert result.load.critical_count == 0
    assert result.load.warning_count > 0


def test_no_result_ever_reports_an_overloaded_package(optimizer, settings, euro_pallet):
    """Das Ergebnis darf keinen ueberlasteten Karton enthalten - sonst waere es
    kein zulaessiger Palettierplan."""
    for load_kg in (8.0, 12.0, 25.0, 60.0, 200.0):
        box = PackageSpec(400.0, 300.0, 200.0, 5.0, max_stack_load_kg=load_kg)
        for pattern_id in ("column", "aligned", "brick", "rotated"):
            result = optimizer.optimize(
                box, euro_pallet, settings.get_pattern(pattern_id), build_constraints(euro_pallet, box)
            )
            assert result.load.critical_count == 0, (
                pattern_id + " bei " + str(load_kg) + " kg: " + str(result.load.critical_count)
                + " ueberlastete Pakete"
            )
