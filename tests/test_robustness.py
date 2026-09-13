"""Belastungs- und Randfaelle (Meilenstein 11).

Geprueft wird, was passiert, wenn die Eingaben an die Grenzen gehen: winzige
und riesige Masse, sehr viele Sauger, viele Pakete, fehlende oder kaputte
Konfiguration, schnelle Aenderungen und parallele Jobs.

Die Erwartung ist durchgaengig dieselbe: ein klares Ergebnis oder eine klare
Meldung - niemals ein Absturz, eine Endlosschleife oder eine still
verschluckte Ausnahme.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest

from app.config.settings_service import SettingsService
from app.core.cancellation import CancellationToken
from app.core.errors import ErrorReporter, Severity
from app.dto.package import PackageSpec, validate_package
from app.dto.vacuum import VacuumInput, VacuumPlateSpec
from app.engines.palletizing.optimizer import PalletOptimizer, PalletizingError, build_constraints
from app.engines.patterns import PatternRequest, available_strategies, generate
from app.engines.vacuum.calculator import VacuumCalculator, VacuumError
from app.engines.vacuum.layout import SuctionLayoutEngine


# Extreme Masse ----------------------------------------------------------------

@pytest.mark.parametrize(
    "length,width,height,weight",
    [
        (20.0, 20.0, 20.0, 0.01),        # sehr klein, aber noch sinnvoll
        (1200.0, 800.0, 1600.0, 800.0),  # fuellt die Palette allein
        (1200.0, 800.0, 1.0, 0.5),       # papierduenn
        (5.0, 1200.0, 5.0, 0.1),         # extrem laenglich
    ],
)
def test_extreme_package_dimensions_do_not_crash(settings, euro_pallet, length, width, height, weight):
    package = PackageSpec(length, width, height, weight)
    assert validate_package(package).ok

    try:
        result = PalletOptimizer().optimize(
            package, euro_pallet, settings.get_pattern("auto"), build_constraints(euro_pallet, package)
        )
    except PalletizingError:
        return  # Eine klare Absage ist ein gueltiges Ergebnis.

    assert result.total_count > 0
    assert result.total_weight_kg <= euro_pallet.max_load_kg + 1e-6
    assert result.total_load_height_mm <= euro_pallet.max_load_height_mm + 1e-6


def test_nan_and_infinity_are_rejected():
    """Spezifikation 11: keine NaN- oder Unendlich-Werte."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        report = validate_package(PackageSpec(bad, 300.0, 200.0, 5.0))
        assert not report.ok
        assert report.for_field("length_mm")


def test_zero_and_negative_values_are_rejected():
    assert not validate_package(PackageSpec(0.0, 300.0, 200.0, 5.0)).ok
    assert not validate_package(PackageSpec(-400.0, 300.0, 200.0, 5.0)).ok
    assert not validate_package(PackageSpec(400.0, 300.0, 200.0, 0.0)).ok


def test_metre_instead_of_millimetre_is_caught():
    """Die haeufigste Verwechslung: 0,4 statt 400."""
    report = validate_package(PackageSpec(400000.0, 300.0, 200.0, 5.0))
    assert not report.ok
    assert "mm erwartet" in report.for_field("length_mm")[0].message


def test_absurdly_small_package_is_refused_not_computed(settings, euro_pallet):
    """Ein Paket von 1 x 1 mm ergaebe 960000 Platzierungen je Lage.

    Das ist keine Palettierung mehr, sondern eine Einheitenverwechslung. Die
    Abweisung muss vor dem Rechnen erfolgen - sonst kostet sie Sekunden,
    Hunderte Megabyte und eine Ansicht, die sich nicht mehr zeichnen laesst.
    """
    tiny = PackageSpec(1.0, 1.0, 1.0, 0.001)

    started = time.perf_counter()
    with pytest.raises(PalletizingError, match="je Lage"):
        PalletOptimizer().optimize(
            tiny, euro_pallet, settings.get_pattern("auto"), build_constraints(euro_pallet, tiny)
        )
    assert time.perf_counter() - started < 0.5, "Die Abweisung muss sofort kommen"


def test_the_limits_do_not_block_realistic_packages(settings, euro_pallet):
    """Die Grenzen duerfen keinen praxisnahen Fall treffen.

    Kartons von 40 x 30 x 25 mm ergeben auf einer Europalette 800 Stueck je
    Lage und 52800 insgesamt. Das ist eine richtige Antwort auf eine richtige
    Frage und darf nicht an einer Obergrenze scheitern.
    """
    small = PackageSpec(40.0, 30.0, 25.0, 0.02)
    result = PalletOptimizer().optimize(
        small, euro_pallet, settings.get_pattern("aligned"), build_constraints(euro_pallet, small)
    )
    assert result.per_layer_count == 800
    assert result.total_count > 50_000


def test_large_stack_with_load_check_stays_fast(settings, euro_pallet):
    """Die Lastkaskade muss auch bei sehr dichten Paletten schnell bleiben.

    Ohne Rasterindex vergleicht sie jedes Paket mit jedem darunter: gemessene
    fuenfundsiebzig Sekunden fuer diesen Fall. Mit Index unter einer Sekunde.
    Der Test haelt den Unterschied fest, damit der Index nicht unbemerkt
    wieder herausfaellt.
    """
    dense = PackageSpec(20.0, 20.0, 20.0, 0.01, max_stack_load_kg=2.0)

    started = time.perf_counter()
    result = PalletOptimizer().optimize(
        dense, euro_pallet, settings.get_pattern("aligned"), build_constraints(euro_pallet, dense)
    )
    elapsed = time.perf_counter() - started

    assert result.total_count > 100_000
    assert result.load.checked is True
    assert elapsed < 10.0, "Lastkaskade braucht " + format(elapsed, ".1f") + " s - Rasterindex pruefen"


def test_load_analysis_is_skipped_without_a_limit(settings, euro_pallet):
    """Ohne Grenzwert gibt es nichts zu pruefen - und nichts zu rechnen."""
    free = PackageSpec(20.0, 20.0, 20.0, 0.01, max_stack_load_kg=0.0)

    started = time.perf_counter()
    result = PalletOptimizer().optimize(
        free, euro_pallet, settings.get_pattern("aligned"), build_constraints(euro_pallet, free)
    )
    elapsed = time.perf_counter() - started

    assert result.load.checked is False
    assert result.load.per_package == ()
    assert elapsed < 3.0


# Grosse Instanzen -------------------------------------------------------------

def test_large_pallet_with_small_packages_stays_fast(settings):
    """Eine ISO-Palette mit kleinen Kartons: ueber tausend Platzierungen."""
    pallet = settings.get_pallet("iso_1200x1200")
    small = PackageSpec(100.0, 80.0, 60.0, 0.4, max_stack_load_kg=40.0)

    started = time.perf_counter()
    result = PalletOptimizer().optimize(
        small, pallet, settings.get_pattern("aligned"), build_constraints(pallet, small)
    )
    elapsed = time.perf_counter() - started

    assert result.total_count > 1000
    assert elapsed < 20.0, "Grosse Instanz braucht " + format(elapsed, ".1f") + " s"


def test_every_strategy_survives_a_large_instance():
    request = PatternRequest(1200.0, 1200.0, 60.0, 50.0)
    for strategy in available_strategies():
        if strategy in ("max_count", "auto"):
            continue  # decken die uebrigen bereits ab
        layout = generate(strategy, request)
        assert layout.count >= 0


def test_many_suction_cups(settings):
    """Eine grosse Platte mit kleinen Saugern: mehrere tausend Positionen."""
    from app.engines.vacuum.layout import MAX_CUP_POSITIONS

    plate = VacuumPlateSpec(length_mm=2000.0, width_mm=1500.0, edge_margin_mm=10.0, min_spacing_mm=2.0)
    cup = settings.get_suction_cup("spb2_20")

    started = time.perf_counter()
    layout = SuctionLayoutEngine().distribute(cup, plate)
    elapsed = time.perf_counter() - started

    assert layout.count > 3000
    assert layout.count <= MAX_CUP_POSITIONS
    assert elapsed < 5.0


def test_automatic_layout_is_capped_and_says_so(settings):
    """Die Hoechstbestueckung einer sehr grossen Platte wird begrenzt.

    Begrenzt statt abgewiesen: das Ergebnis bleibt brauchbar, und die Meldung
    sagt, wie man mehr bekommt.
    """
    from app.engines.vacuum.layout import MAX_CUP_POSITIONS

    plate = VacuumPlateSpec(length_mm=3000.0, width_mm=2500.0, edge_margin_mm=5.0, min_spacing_mm=1.0)
    layout = SuctionLayoutEngine().distribute(settings.get_suction_cup("spb2_20"), plate)

    assert layout.max_count > MAX_CUP_POSITIONS
    assert layout.count <= MAX_CUP_POSITIONS
    assert any("Saugeranzahl ausdruecklich vorgeben" in note for note in layout.notes)


def test_an_explicit_count_above_the_cap_is_still_honoured(settings):
    """Wer die Zahl ausdruecklich vorgibt, bekommt sie auch oberhalb der Grenze."""
    plate = VacuumPlateSpec(length_mm=3000.0, width_mm=2500.0, edge_margin_mm=5.0, min_spacing_mm=1.0)
    layout = SuctionLayoutEngine().distribute(settings.get_suction_cup("spb2_20"), plate, wanted_count=6000)
    assert layout.count == 6000


def test_many_cups_and_many_packages_together(settings):
    """Der teuerste Fall: jede Saugerposition gegen jedes Paket pruefen."""
    plate = VacuumPlateSpec(length_mm=1600.0, width_mm=1200.0, edge_margin_mm=20.0, min_spacing_mm=8.0)
    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(200.0, 150.0, 120.0, 2.0),
        plate=plate,
        cup=settings.get_suction_cup("spb2_25"),
        package_count=48,
        pump=defaults.pump,
        leakage=defaults.leakage,
        restrictor=defaults.restrictor,
    )

    started = time.perf_counter()
    result = VacuumCalculator().calculate(request)
    elapsed = time.perf_counter() - started

    assert result.total_cup_count > 500
    assert len(result.package_rects) == 48
    assert result.sealed_count > 0
    assert elapsed < 20.0, "Grosse Vakuuminstanz braucht " + format(elapsed, ".1f") + " s"


def test_more_packages_than_the_plate_holds_are_arranged_anyway(settings):
    """Fuenfzig Pakete auf einer Platte von 600 x 400 mm.

    Sie passen nicht darauf - angeordnet werden sie trotzdem, und der Ueberhang
    wird gemeldet. Die Platte begrenzt nur, wo Sauger sitzen koennen.
    """
    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=VacuumPlateSpec(600.0, 400.0),
        cup=settings.get_suction_cup("spb2_30"),
        package_count=50,
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
    )
    result = VacuumCalculator().calculate(request)

    assert len(result.package_rects) == 50
    assert any("ragen ueber die Platte hinaus" in w for w in result.warnings)


# Grenzwerte des Vakuums --------------------------------------------------------

def test_zero_flow_pump_gives_a_clear_result(settings):
    """Ein Erzeuger ohne Leistung: kein Vakuum, keine Kraft, klare Aussage."""
    from app.dto.vacuum import PumpSpec

    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=defaults.plate,
        cup=settings.get_suction_cup("spb2_30"),
        package_count=4,
        pump=PumpSpec(nominal_flow_m3s=0.0, max_vacuum_pa=85000.0),
        leakage=defaults.leakage,
        restrictor=defaults.restrictor,
    )
    result = VacuumCalculator().calculate(request)

    assert result.max_package_mass_kg >= 0.0
    assert result.status.value in ("safe", "marginal", "insufficient")


def test_extremely_permeable_carton(settings):
    from app.dto.vacuum import LeakageModel, LeakageSpec

    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=defaults.plate,
        cup=settings.get_suction_cup("spb2_30"),
        package_count=4,
        pump=defaults.pump,
        leakage=LeakageSpec(LeakageModel.FLOW_PER_AREA, permeability_value=50.0, reference_vacuum_pa=60000.0),
        restrictor=defaults.restrictor,
    )
    result = VacuumCalculator().calculate(request)

    assert result.achieved_vacuum_pa < result.target_vacuum_pa
    assert result.flow.workpiece_m3s > 0.0
    assert any("nicht erreicht" in w for w in result.warnings)


def test_plate_smaller_than_one_cup(settings):
    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=VacuumPlateSpec(30.0, 30.0, edge_margin_mm=20.0),
        cup=settings.get_suction_cup("spb2_50"),
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
    )
    with pytest.raises(VacuumError):
        VacuumCalculator().calculate(request)


def test_extreme_safety_factor(settings):
    defaults = settings.get_vacuum_defaults()
    base = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=defaults.plate, cup=settings.get_suction_cup("spb2_30"), package_count=4,
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
    )
    result = VacuumCalculator().calculate(replace(base, safety_factor=20.0))
    assert result.max_package_mass_kg > 0.0
    assert result.status.value == "insufficient"


# Konfiguration ----------------------------------------------------------------

def test_missing_configuration_directory(tmp_path):
    reporter = ErrorReporter()
    service = SettingsService(tmp_path / "gibt_es_nicht", reporter)
    status = service.load()

    assert status.ok is False
    assert service.get_pallets(), "Notfalldaten muessen einspringen"
    assert reporter.problems.count(Severity.WARNING) > 0


def test_all_configuration_files_broken(tmp_path):
    reporter = ErrorReporter()
    for name in ("pallets.json", "pallet_patterns.json", "suction_cups.json", "vacuum_defaults.json"):
        (tmp_path / name).write_text("{{{ kaputt", encoding="utf-8")

    service = SettingsService(tmp_path, reporter)
    status = service.load()

    assert status.ok is False
    assert len(status.failed_files) == 4
    assert service.get_pallets() and service.get_patterns() and service.get_suction_cups()
    assert service.get_vacuum_defaults().plate.length_mm > 0


def test_application_starts_with_broken_configuration(tmp_path):
    """Die Anwendung muss auch mit zerlegter Konfiguration startbar bleiben -
    sonst kann man den Fehler nicht einmal ansehen."""
    from app.application import Application

    (tmp_path / "pallets.json").write_text("[]", encoding="utf-8")
    app = Application(config_directory=tmp_path, log_directory=tmp_path / "logs")
    result = app.startup()

    assert result.ok is True
    assert result.notes, "Die Beanstandungen muessen gemeldet werden"
    app.shutdown()


def test_configuration_with_wrong_types(tmp_path):
    reporter = ErrorReporter()
    payload = {"pallets": [
        {"id": "text", "length_mm": "zwoelfhundert", "width_mm": 800,
         "max_load_kg": 1000, "max_load_height_mm": 1500},
        {"id": "null", "length_mm": None, "width_mm": 800,
         "max_load_kg": 1000, "max_load_height_mm": 1500},
        {"id": "liste", "length_mm": [1200], "width_mm": 800,
         "max_load_kg": 1000, "max_load_height_mm": 1500},
    ]}
    (tmp_path / "pallets.json").write_text(json.dumps(payload), encoding="utf-8")

    service = SettingsService(tmp_path, reporter)
    service.load()
    assert all(p.id not in ("text", "null", "liste") for p in service.get_pallets())


# Abbruch und Wiederholbarkeit --------------------------------------------------

def test_cancellation_during_a_large_run(settings):
    """Ein Abbruch muss auch mitten in einer grossen Rechnung greifen."""
    from app.core.cancellation import CancelledError

    pallet = settings.get_pallet("iso_1200x1200")
    small = PackageSpec(80.0, 60.0, 50.0, 0.3)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(CancelledError):
        PalletOptimizer().optimize(
            small, pallet, settings.get_pattern("auto"), build_constraints(pallet, small), token=token
        )


def test_repeated_runs_stay_identical(settings, euro_pallet, package):
    """Spezifikation 39, ueber viele Wiederholungen."""
    optimizer = PalletOptimizer()
    pattern = settings.get_pattern("auto")
    constraints = build_constraints(euro_pallet, package)

    reference = optimizer.optimize(package, euro_pallet, pattern, constraints)
    signature = [(p.x_mm, p.y_mm, p.z_mm, p.rotated) for l in reference.layers for p in l.placements]

    for _ in range(5):
        again = optimizer.optimize(package, euro_pallet, pattern, constraints)
        assert [(p.x_mm, p.y_mm, p.z_mm, p.rotated) for l in again.layers for p in l.placements] == signature


def test_vacuum_runs_stay_identical(settings):
    defaults = settings.get_vacuum_defaults()
    request = VacuumInput(
        package=PackageSpec(400.0, 300.0, 200.0, 5.0),
        plate=defaults.plate, cup=settings.get_suction_cup("spb2_30"), package_count=4,
        pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
    )
    calculator = VacuumCalculator()
    reference = calculator.calculate(request)

    for _ in range(5):
        again = calculator.calculate(request)
        assert again.achieved_vacuum_pa == reference.achieved_vacuum_pa
        assert again.max_package_mass_kg == reference.max_package_mass_kg
        assert again.sealed_count == reference.sealed_count


# Parallele Jobs ---------------------------------------------------------------

def test_parallel_jobs_of_both_modules(qt_app, tmp_path):
    """Palettierung und Vakuum gleichzeitig - getrennte Pools, getrennte Kanaele."""
    from pathlib import Path

    from app.application import Application

    root = Path(__file__).resolve().parent.parent
    app = Application(config_directory=root / "config", log_directory=tmp_path / "logs")
    app.startup()
    try:
        app.state.set_package(PackageSpec(400.0, 300.0, 200.0, 5.0, max_stack_load_kg=50.0))
        pallet = app.settings.get_pallet("euro_1200x800")
        pattern = app.settings.get_pattern("auto")
        defaults = app.settings.get_vacuum_defaults()

        pallet_results: list = []
        vacuum_results: list = []
        app.pallets.result_ready.connect(pallet_results.append)
        app.vacuum.result_ready.connect(vacuum_results.append)

        package = app.state.snapshot().package
        app.pallets.calculate_async(
            package, pallet, pattern, build_constraints(pallet, package), app.state.revision
        )
        app.vacuum.calculate_async(
            VacuumInput(
                package=package, plate=defaults.plate,
                cup=app.settings.get_suction_cup("spb2_30"), package_count=4,
                pump=defaults.pump, leakage=defaults.leakage, restrictor=defaults.restrictor,
            ),
            app.state.revision,
        )

        deadline = time.perf_counter() + 30.0
        while time.perf_counter() < deadline:
            qt_app.processEvents()
            if app.jobs.active_count == 0:
                break
            time.sleep(0.005)
        qt_app.processEvents()

        assert len(pallet_results) == 1
        assert len(vacuum_results) == 1
        assert app.jobs.counters()["fehlgeschlagen"] == 0
    finally:
        app.shutdown()


def test_burst_of_requests_leaves_exactly_one_result(qt_app, tmp_path):
    """Zwanzig Anfragen in Folge - genau die letzte darf ankommen."""
    from pathlib import Path

    from app.application import Application

    root = Path(__file__).resolve().parent.parent
    app = Application(config_directory=root / "config", log_directory=tmp_path / "logs")
    app.startup()
    try:
        app.state.set_package(PackageSpec(400.0, 300.0, 200.0, 5.0))
        pallet = app.settings.get_pallet("euro_1200x800")
        pattern = app.settings.get_pattern("aligned")

        delivered: list = []
        superseded: list = []
        app.pallets.result_ready.connect(delivered.append)
        app.pallets.superseded.connect(superseded.append)

        package = app.state.snapshot().package
        for height in range(400, 1400, 50):
            app.pallets.calculate_async(
                package, pallet, pattern,
                build_constraints(pallet, package, max_height_mm=float(height)),
                app.state.revision,
            )

        deadline = time.perf_counter() + 30.0
        while time.perf_counter() < deadline:
            qt_app.processEvents()
            if app.jobs.active_count == 0:
                break
            time.sleep(0.005)
        qt_app.processEvents()

        assert len(delivered) <= 1, "Nur das juengste Ergebnis darf die Anzeige erreichen"
        if delivered:
            assert delivered[0].meta.request_id == app.gate.latest("pallet")
        assert app.jobs.counters()["fehlgeschlagen"] == 0
    finally:
        app.shutdown()
