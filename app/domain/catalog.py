"""Die Konfigurationskataloge: laden, pruefen, bereitstellen.

Drei Arbeitsgaenge an denselben Dateien, deshalb an einem Ort:

    ConfigLoader      liest die JSON-Dateien und meldet Lesefehler
    parse_*           macht aus rohen dicts ein geprueftes Datenobjekt
    SettingsService   haelt das Ergebnis und gibt es heraus

Die Dateien liegen NEBEN der Programmdatei, nicht darin - nur so laesst sich
ein neuer Saugertyp oder eine neue Palette nach der Auslieferung ergaenzen.
Wo gesucht wird, steht in app/infra/paths.py.

Zusammengelegt aus config/loader.py, config/schema.py und
config/settings_service.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from app.infra.errors import AppError, ErrorReporter, Severity
import math
from typing import Any, Callable
from app.infra.errors import ErrorReporter
from app.domain.units import lpm_to_m3s
from app.pallet.models import PalletSpec, PatternSpec, ZMode
from app.vacuum.models import RestrictorMode, RestrictorSpec, SuctionCupSpec
from app.vacuum.models import GripDirection, LeakageModel, LeakageSpec, PumpSpec, VacuumPlateSpec
import threading
from app.vacuum.models import SuctionCupSpec
from app.vacuum.models import PumpSpec, VacuumPlateSpec


# ---------------------------------------------------------------------------
# loader.py
# ---------------------------------------------------------------------------
"""Rohes Einlesen der Konfigurationsdateien.

Die einzige Stelle im Programm, die JSON-Dateien oeffnet. Alles darueber
arbeitet mit den bereits geprueften Objekten aus schema.py.

Fehlertoleranz ist hier Programm (Spezifikation 27): eine fehlende oder
beschaedigte Datei darf den Start nicht verhindern. Sie wird gemeldet, und der
Aufrufer arbeitet mit den eingebauten Ausweichdaten weiter. Nur so bleibt die
Anwendung auch dann bedienbar, wenn jemand eine Datei beim Bearbeiten zerlegt
hat - und genau dann braucht man sie, um den Fehler zu sehen.

Schluessel, die mit einem Unterstrich beginnen, sind Kommentare. JSON kennt
keine, und ein Kommentarfeld ist die einzige Moeglichkeit, die Herkunft eines
Kennwerts in der Datei selbst festzuhalten.
"""

@dataclass(frozen=True, slots=True)
class LoadedFile:
    """Was beim Lesen einer Konfigurationsdatei herauskam."""

    name: str
    path: Path | None
    data: dict[str, Any]
    ok: bool
    message: str = ""

    @property
    def used_fallback(self) -> bool:
        return not self.ok


def strip_comments(data: dict[str, Any]) -> dict[str, Any]:
    """Entfernt Kommentarschluessel rekursiv aus geladenen Daten."""
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        if isinstance(value, dict):
            cleaned[key] = strip_comments(value)
        elif isinstance(value, list):
            cleaned[key] = [strip_comments(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


class ConfigLoader:
    """Liest die Konfigurationsdateien eines Verzeichnisses."""

    def __init__(self, directory: Path, reporter: ErrorReporter) -> None:
        self.directory = directory
        self._reporter = reporter

    def load(self, filename: str) -> LoadedFile:
        path = self.directory / filename

        if not path.is_file():
            message = "Konfigurationsdatei fehlt: " + str(path)
            self._reporter.report(
                AppError(
                    Severity.WARNING, "config", message,
                    message_key="config:missing:" + filename,
                    technical_message="Es werden die eingebauten Vorgabewerte verwendet.",
                )
            )
            return LoadedFile(filename, None, {}, ok=False, message=message)

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            message = "Konfigurationsdatei nicht lesbar: " + str(path)
            self._reporter.report(
                AppError.from_exception(
                    exc, source="config", severity=Severity.WARNING,
                    message=message, message_key="config:unreadable:" + filename,
                )
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            message = (
                "Konfigurationsdatei " + filename + " ist kein gueltiges JSON "
                "(Zeile " + str(exc.lineno) + ", Spalte " + str(exc.colno) + "): " + exc.msg
            )
            self._reporter.report(
                AppError(
                    Severity.ERROR, "config", message,
                    message_key="config:invalid:" + filename,
                    technical_message=str(path),
                )
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        if not isinstance(data, dict):
            message = "Konfigurationsdatei " + filename + " enthaelt kein Objekt auf oberster Ebene"
            self._reporter.report(
                AppError(Severity.ERROR, "config", message, message_key="config:shape:" + filename)
            )
            return LoadedFile(filename, path, {}, ok=False, message=message)

        return LoadedFile(filename, path, strip_comments(data), ok=True)


# ---------------------------------------------------------------------------
# schema.py
# ---------------------------------------------------------------------------
"""Pruefung und Umwandlung der Konfigurationsdaten in DTOs.

Der Grundsatz hier heisst: ein fehlerhafter Eintrag kostet diesen Eintrag, nicht
die ganze Datei. Wer eine Palette mit negativer Laenge eintraegt, soll die
uebrigen Paletten weiter im Auswahlfeld sehen und eine klare Meldung zu der
einen bekommen - nicht eine leere Anwendung.

Pflichtfelder ohne sinnvollen Ersatzwert fuehren zum Verwerfen des Eintrags.
Fehlende Felder mit vertretbarem Standardwert werden ergaenzt und als Hinweis
gemeldet. Was davon zutrifft, steht bei jedem Feld in der jeweiligen Liste.
"""

CONFIG_VERSION = 1


class ConfigError(ValueError):
    """Ein Eintrag ist unbrauchbar und wird verworfen."""


@dataclass(frozen=True, slots=True)
class LeakagePreset:
    """Vorlage fuer ein Permeabilitaetsmodell, waehlbar in der Oberflaeche."""

    id: str
    name: str
    spec: LeakageSpec


@dataclass(frozen=True, slots=True)
class VacuumDefaults:
    """Alle Vorgabewerte des Vakuumtabs."""

    plate: VacuumPlateSpec
    pump: PumpSpec
    restrictor: RestrictorSpec
    leakage: LeakageSpec
    leakage_presets: tuple[LeakagePreset, ...] = ()
    default_cup_id: str = ""
    arrangement_id: str = "grid_spread"
    target_vacuum_pa: float = 60000.0
    ambient_pa: float = 101325.0
    safety_factor: float = 2.0
    acceleration_ms2: float = 0.0
    grip: GripDirection = GripDirection.HORIZONTAL
    friction_factor: float = 0.5
    package_count: int = 1
    count_partial_as_sealed: bool = False
    solve_operating_point: bool = True
    max_cup_count: int = 2000
    min_plate_edge_mm: float = 50.0
    max_plate_edge_mm: float = 3000.0
    marginal_margin_ratio: float = 0.1


# Feldhelfer -------------------------------------------------------------------

def _number(entry: dict, key: str, *, required: bool = True, default: float = 0.0,
            minimum: float | None = None, maximum: float | None = None) -> float:
    if key not in entry or entry[key] is None:
        if required:
            raise ConfigError("Feld '" + key + "' fehlt")
        return default
    value = entry[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("Feld '" + key + "' ist keine Zahl: " + repr(value))
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ConfigError("Feld '" + key + "' ist kein endlicher Wert")
    if minimum is not None and value < minimum:
        raise ConfigError("Feld '" + key + "' unterschreitet " + format(minimum, "g"))
    if maximum is not None and value > maximum:
        raise ConfigError("Feld '" + key + "' ueberschreitet " + format(maximum, "g"))
    return value


def _text(entry: dict, key: str, *, required: bool = True, default: str = "") -> str:
    value = entry.get(key)
    if value is None or value == "":
        if required:
            raise ConfigError("Feld '" + key + "' fehlt")
        return default
    return str(value)


def _flag(entry: dict, key: str, default: bool = False) -> bool:
    value = entry.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "ja")


def _enum(entry: dict, key: str, enum_cls, default):
    raw = entry.get(key)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    for member in enum_cls:
        if member.value == text:
            return member
    raise ConfigError("Feld '" + key + "' kennt den Wert '" + str(raw) + "' nicht")


def _parse_list(
    data: dict, section: str, filename: str, parse: Callable[[dict], Any], reporter: ErrorReporter
) -> tuple[Any, ...]:
    """Liest eine Liste von Eintraegen und ueberspringt die unbrauchbaren."""
    raw_entries = data.get(section)
    if not isinstance(raw_entries, list):
        if data:
            reporter.warning("config", "Abschnitt '" + section + "' fehlt in " + filename)
        return ()

    parsed: list[Any] = []
    seen_ids: set[str] = set()
    for position, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            reporter.warning("config", filename + ": Eintrag " + str(position + 1) + " ist kein Objekt")
            continue
        try:
            item = parse(raw)
        except ConfigError as exc:
            reporter.warning(
                "config",
                filename + ": Eintrag '" + str(raw.get("id", position + 1)) + "' verworfen - " + str(exc),
            )
            continue
        identifier = getattr(item, "id", "")
        if identifier in seen_ids:
            reporter.warning("config", filename + ": doppelte Kennung '" + identifier + "' uebersprungen")
            continue
        seen_ids.add(identifier)
        parsed.append(item)
    return tuple(parsed)


# Paletten ---------------------------------------------------------------------

def _parse_pallet(entry: dict) -> PalletSpec:
    length = _number(entry, "length_mm", minimum=1.0, maximum=10000.0)
    width = _number(entry, "width_mm", minimum=1.0, maximum=10000.0)
    return PalletSpec(
        id=_text(entry, "id"),
        name=_text(entry, "name", required=False, default=_text(entry, "id")),
        length_mm=length,
        width_mm=width,
        max_load_kg=_number(entry, "max_load_kg", minimum=0.0, maximum=100000.0),
        max_load_height_mm=_number(entry, "max_load_height_mm", minimum=1.0, maximum=10000.0),
        deck_height_mm=_number(entry, "deck_height_mm", required=False, default=144.0, minimum=0.0, maximum=1000.0),
        tare_weight_kg=_number(entry, "tare_weight_kg", required=False, default=0.0, minimum=0.0, maximum=1000.0),
        overhang_mm=_number(entry, "overhang_mm", required=False, default=0.0, minimum=0.0, maximum=500.0),
        edge_clearance_mm=_number(entry, "edge_clearance_mm", required=False, default=0.0, minimum=0.0, maximum=500.0),
    )


def parse_pallets(data: dict, reporter: ErrorReporter) -> tuple[PalletSpec, ...]:
    return _parse_list(data, "pallets", "pallets.json", _parse_pallet, reporter)


# Muster -----------------------------------------------------------------------

def _parse_pattern(entry: dict) -> PatternSpec:
    options = entry.get("options")
    return PatternSpec(
        id=_text(entry, "id"),
        name=_text(entry, "name", required=False, default=_text(entry, "id")),
        strategy=_text(entry, "strategy"),
        z_mode=_enum(entry, "z_mode", ZMode, ZMode.MIRROR),
        description=_text(entry, "description", required=False),
        options=dict(options) if isinstance(options, dict) else {},
        min_package_edge_mm=_number(entry, "min_package_edge_mm", required=False, default=0.0, minimum=0.0),
        max_package_edge_mm=_number(entry, "max_package_edge_mm", required=False, default=0.0, minimum=0.0),
    )


def parse_patterns(data: dict, reporter: ErrorReporter) -> tuple[PatternSpec, ...]:
    return _parse_list(data, "patterns", "pallet_patterns.json", _parse_pattern, reporter)


# Sauger -----------------------------------------------------------------------

def _parse_cup(entry: dict) -> SuctionCupSpec:
    nominal = _number(entry, "nominal_diameter_mm", minimum=1.0, maximum=500.0)
    effective = _number(entry, "effective_diameter_mm", minimum=0.5, maximum=500.0)
    if effective > nominal:
        raise ConfigError("effective_diameter_mm ist groesser als nominal_diameter_mm")
    outer = _number(entry, "outer_diameter_mm", required=False, default=nominal, minimum=1.0, maximum=600.0)
    sealing = _number(entry, "sealing_lip_diameter_mm", required=False, default=outer, minimum=0.5, maximum=600.0)
    if sealing > outer:
        raise ConfigError("sealing_lip_diameter_mm ist groesser als outer_diameter_mm")
    return SuctionCupSpec(
        id=_text(entry, "id"),
        name=_text(entry, "name", required=False, default=_text(entry, "id")),
        manufacturer=_text(entry, "manufacturer", required=False),
        family=_text(entry, "family", required=False),
        nominal_diameter_mm=nominal,
        effective_diameter_mm=effective,
        sealing_lip_diameter_mm=sealing,
        outer_diameter_mm=outer,
        bore_diameter_mm=_number(entry, "bore_diameter_mm", minimum=0.1, maximum=100.0),
        theoretical_force_n=_number(entry, "theoretical_force_n", minimum=0.0, maximum=100000.0),
        reference_vacuum_pa=_number(
            entry, "reference_vacuum_mbar", required=False, default=600.0, minimum=1.0, maximum=1013.0
        ) * 100.0,
        pull_off_force_n=_number(entry, "pull_off_force_n", required=False, default=0.0, minimum=0.0),
        lateral_force_n=_number(entry, "lateral_force_n", required=False, default=0.0, minimum=0.0),
        volume_cm3=_number(entry, "volume_cm3", required=False, default=0.0, minimum=0.0),
        min_workpiece_radius_mm=_number(entry, "min_workpiece_radius_mm", required=False, default=0.0, minimum=0.0),
        hose_inner_diameter_mm=_number(entry, "hose_inner_diameter_mm", required=False, default=0.0, minimum=0.0),
        stroke_mm=_number(entry, "stroke_mm", required=False, default=0.0, minimum=0.0),
        material=_text(entry, "material", required=False),
        folds_count=_number(entry, "folds_count", required=False, default=0.0, minimum=0.0),
        datasheet_url=_text(entry, "datasheet_url", required=False),
    )


def parse_suction_cups(data: dict, reporter: ErrorReporter) -> tuple[SuctionCupSpec, ...]:
    return _parse_list(data, "suction_cups", "suction_cups.json", _parse_cup, reporter)


# Vakuum-Vorgaben --------------------------------------------------------------

def _parse_leakage(entry: dict) -> LeakageSpec:
    return LeakageSpec(
        model=_enum(entry, "model", LeakageModel, LeakageModel.NONE),
        permeability_value=_number(entry, "permeability_value", required=False, default=0.0, minimum=0.0),
        unit_label=_text(entry, "unit_label", required=False),
        reference_vacuum_pa=_number(entry, "reference_vacuum_pa", required=False, default=60000.0, minimum=1.0),
        pressure_exponent_factor=_number(
            entry, "pressure_exponent_factor", required=False, default=1.0, minimum=0.1, maximum=2.0
        ),
    )


def _parse_curve(raw: Any) -> tuple[tuple[float, float], ...]:
    """Stuetzpunkte der Pumpenkennlinie, aufsteigend nach Vakuum sortiert."""
    if not isinstance(raw, list):
        return ()
    points: list[tuple[float, float]] = []
    for item in raw:
        if isinstance(item, dict):
            vacuum = item.get("vacuum_pa")
            flow = item.get("flow_m3s")
            if flow is None and "flow_lpm" in item:
                flow = lpm_to_m3s(float(item["flow_lpm"]))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            vacuum, flow = item
        else:
            continue
        try:
            pair = (float(vacuum), float(flow))
        except (TypeError, ValueError):
            continue
        if pair[0] >= 0.0 and pair[1] >= 0.0:
            points.append(pair)
    return tuple(sorted(points))


def parse_vacuum_defaults(data: dict, reporter: ErrorReporter) -> VacuumDefaults:
    """Liest vacuum_defaults.json. Fehlende Abschnitte werden ergaenzt."""
    plate_raw = data.get("plate", {}) if isinstance(data.get("plate"), dict) else {}
    pump_raw = data.get("pump", {}) if isinstance(data.get("pump"), dict) else {}
    restrictor_raw = data.get("restrictor", {}) if isinstance(data.get("restrictor"), dict) else {}
    leakage_raw = data.get("leakage", {}) if isinstance(data.get("leakage"), dict) else {}
    operation = data.get("operation", {}) if isinstance(data.get("operation"), dict) else {}
    limits = data.get("limits", {}) if isinstance(data.get("limits"), dict) else {}
    assumptions = data.get("assumptions", {}) if isinstance(data.get("assumptions"), dict) else {}

    def _guarded(parse: Callable[[], Any], fallback: Any, what: str) -> Any:
        try:
            return parse()
        except ConfigError as exc:
            reporter.warning("config", "vacuum_defaults.json: " + what + " unbrauchbar (" + str(exc) + "), Vorgabe verwendet")
            return fallback

    plate = _guarded(
        lambda: VacuumPlateSpec(
            length_mm=_number(plate_raw, "length_mm", required=False, default=800.0, minimum=1.0, maximum=10000.0),
            width_mm=_number(plate_raw, "width_mm", required=False, default=600.0, minimum=1.0, maximum=10000.0),
            thickness_mm=_number(plate_raw, "thickness_mm", required=False, default=15.0, minimum=0.0, maximum=500.0),
            edge_margin_mm=_number(plate_raw, "edge_margin_mm", required=False, default=20.0, minimum=0.0, maximum=1000.0),
            min_spacing_mm=_number(plate_raw, "min_spacing_mm", required=False, default=5.0, minimum=0.0, maximum=1000.0),
        ),
        VacuumPlateSpec(800.0, 600.0),
        "Abschnitt 'plate'",
    )

    pump = _guarded(
        lambda: PumpSpec(
            name=_text(pump_raw, "name", required=False, default="Vakuumerzeuger"),
            nominal_flow_m3s=_number(pump_raw, "nominal_flow_m3s", required=False, default=0.0, minimum=0.0),
            max_vacuum_pa=_number(pump_raw, "max_vacuum_pa", required=False, default=85000.0, minimum=1.0, maximum=101325.0),
            curve_points=_parse_curve(pump_raw.get("curve_points")),
        ),
        PumpSpec(),
        "Abschnitt 'pump'",
    )

    restrictor = _guarded(
        lambda: RestrictorSpec(
            mode=_enum(restrictor_raw, "mode", RestrictorMode, RestrictorMode.NONE),
            diameter_mm=_number(restrictor_raw, "diameter_mm", required=False, default=1.0, minimum=0.05, maximum=50.0),
            check_valve_leak_ratio=_number(
                restrictor_raw, "check_valve_leak_ratio", required=False, default=0.02, minimum=0.0, maximum=1.0
            ),
            discharge_coefficient_factor=_number(
                restrictor_raw, "discharge_coefficient_factor", required=False, default=0.8, minimum=0.1, maximum=1.0
            ),
        ),
        RestrictorSpec(),
        "Abschnitt 'restrictor'",
    )

    leakage = _guarded(lambda: _parse_leakage(leakage_raw), LeakageSpec(), "Abschnitt 'leakage'")

    presets: list[LeakagePreset] = []
    for raw in data.get("leakage_presets", []) if isinstance(data.get("leakage_presets"), list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            presets.append(
                LeakagePreset(id=_text(raw, "id"), name=_text(raw, "name", required=False, default=_text(raw, "id")),
                              spec=_parse_leakage(raw))
            )
        except ConfigError as exc:
            reporter.warning("config", "vacuum_defaults.json: Leckage-Vorlage verworfen - " + str(exc))

    def _assumption(key: str, default: float) -> float:
        section = assumptions.get(key)
        if isinstance(section, dict) and isinstance(section.get("value"), (int, float)):
            return float(section["value"])
        return default

    return VacuumDefaults(
        plate=plate,
        pump=pump,
        restrictor=restrictor,
        leakage=leakage,
        leakage_presets=tuple(presets),
        default_cup_id=_text(operation, "default_cup_id", required=False),
        arrangement_id=_text(operation, "arrangement", required=False, default="grid_spread"),
        target_vacuum_pa=_number(operation, "target_vacuum_pa", required=False, default=60000.0, minimum=1.0, maximum=101324.0),
        ambient_pa=_number(operation, "ambient_pa", required=False, default=101325.0, minimum=1000.0, maximum=200000.0),
        safety_factor=_number(operation, "safety_factor", required=False, default=2.0, minimum=1.0, maximum=20.0),
        acceleration_ms2=_number(operation, "acceleration_ms2", required=False, default=0.0, minimum=0.0, maximum=200.0),
        grip=_enum(operation, "grip", GripDirection, GripDirection.HORIZONTAL),
        friction_factor=_number(operation, "friction_factor", required=False, default=0.5, minimum=0.01, maximum=2.0),
        package_count=int(_number(operation, "package_count", required=False, default=1.0, minimum=1.0, maximum=1000.0)),
        count_partial_as_sealed=_flag(operation, "count_partial_as_sealed", False),
        solve_operating_point=_flag(operation, "solve_operating_point", True),
        max_cup_count=int(_number(limits, "max_cup_count", required=False, default=2000.0, minimum=1.0, maximum=100000.0)),
        min_plate_edge_mm=_number(limits, "min_plate_edge_mm", required=False, default=50.0, minimum=1.0),
        max_plate_edge_mm=_number(limits, "max_plate_edge_mm", required=False, default=3000.0, minimum=1.0),
        marginal_margin_ratio=_assumption("marginal_margin_ratio", 0.1),
    )


# ---------------------------------------------------------------------------
# settings_service.py
# ---------------------------------------------------------------------------
"""Der einzige erlaubte Zugriffsweg auf Konfigurationsdaten.

Die Oberflaeche ruft get_pallets(), get_patterns(), get_suction_cups() und
get_vacuum_defaults(). Sie oeffnet keine Datei und kennt keinen Dateinamen.
tests/test_architecture.py erzwingt das.

Die Daten liegen nach load() typisiert im Speicher; die Abfragen sind damit
einfache Feldzugriffe und aus dem Oberflaechen-Thread unbedenklich.

Ausweichverhalten: sind nach dem Einlesen keine Paletten, Muster oder Sauger
vorhanden, springen eingebaute Mindestdaten ein. Damit bleibt die Anwendung mit
beschaedigter Konfiguration bedienbar - die Auswahlfelder sind gefuellt, die
Problemliste sagt, was fehlt, und der Benutzer kann die Datei reparieren, statt
vor einem toten Programm zu sitzen.
"""

PALLETS_FILE = "pallets.json"
PATTERNS_FILE = "pallet_patterns.json"
CUPS_FILE = "suction_cups.json"
VACUUM_FILE = "vacuum_defaults.json"


def _builtin_pallets() -> tuple[PalletSpec, ...]:
    """Mindestdatensatz, falls pallets.json unbrauchbar ist."""
    return (
        PalletSpec(
            id="euro_1200x800", name="Europalette (Notfallwert)",
            length_mm=1200.0, width_mm=800.0, max_load_kg=1500.0,
            max_load_height_mm=1650.0, deck_height_mm=144.0, tare_weight_kg=25.0,
        ),
    )


def _builtin_patterns() -> tuple[PatternSpec, ...]:
    """Mindestdatensatz, falls pallet_patterns.json unbrauchbar ist."""
    return (
        PatternSpec(id="auto", name="Automatisch (Notfallwert)", strategy="auto", z_mode=ZMode.MIRROR),
        PatternSpec(id="aligned", name="Ausgerichtet (Notfallwert)", strategy="uniform_grid", z_mode=ZMode.IDENTICAL),
    )


def _builtin_cups() -> tuple[SuctionCupSpec, ...]:
    """Mindestdatensatz, falls suction_cups.json unbrauchbar ist.

    Die Werte stammen aus dem SPB2-Datenblatt und sind hier nur als Notnagel
    dupliziert; massgeblich bleibt die Konfigurationsdatei.
    """
    return (
        SuctionCupSpec(
            id="spb2_30", name="SPB2 30 (Notfallwert)", manufacturer="Schmalz", family="SPB2",
            nominal_diameter_mm=30.0, effective_diameter_mm=16.9, sealing_lip_diameter_mm=31.4,
            outer_diameter_mm=34.0, bore_diameter_mm=4.0, theoretical_force_n=14.4,
            pull_off_force_n=28.4, lateral_force_n=12.8, volume_cm3=12.4,
        ),
    )


@dataclass(frozen=True, slots=True)
class ConfigStatus:
    """Zustandsbericht des Ladevorgangs, fuer Statusleiste und --check."""

    directory: Path
    pallet_count: int
    pattern_count: int
    cup_count: int
    failed_files: tuple[str, ...] = ()
    used_builtin: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed_files and not self.used_builtin


class SettingsService:
    """Haelt die geladene Konfiguration und gibt sie typisiert heraus."""

    def __init__(self, directory: Path, reporter: ErrorReporter) -> None:
        self._directory = directory
        self._reporter = reporter
        self._lock = threading.RLock()
        self._pallets: tuple[PalletSpec, ...] = ()
        self._patterns: tuple[PatternSpec, ...] = ()
        self._cups: tuple[SuctionCupSpec, ...] = ()
        self._vacuum: VacuumDefaults | None = None
        self._status: ConfigStatus | None = None
        self._listeners: list = []

    # Laden --------------------------------------------------------------------

    def load(self) -> ConfigStatus:
        """Liest alle Dateien neu ein. Auch als 'Konfiguration neu laden'
        aus der Oberflaeche aufrufbar."""
        loader = ConfigLoader(self._directory, self._reporter)
        failed: list[str] = []
        builtin: list[str] = []

        pallets_file = loader.load(PALLETS_FILE)
        patterns_file = loader.load(PATTERNS_FILE)
        cups_file = loader.load(CUPS_FILE)
        vacuum_file = loader.load(VACUUM_FILE)

        for entry in (pallets_file, patterns_file, cups_file, vacuum_file):
            if not entry.ok:
                failed.append(entry.name)
            else:
                self._check_version(entry.name, entry.data)

        pallets = parse_pallets(pallets_file.data, self._reporter)
        patterns = parse_patterns(patterns_file.data, self._reporter)
        cups = parse_suction_cups(cups_file.data, self._reporter)
        vacuum = parse_vacuum_defaults(vacuum_file.data, self._reporter)

        if not pallets:
            pallets = _builtin_pallets()
            builtin.append(PALLETS_FILE)
            self._reporter.warning("config", "Keine gueltige Palette gefunden - Notfalldaten aktiv")
        if not patterns:
            patterns = _builtin_patterns()
            builtin.append(PATTERNS_FILE)
            self._reporter.warning("config", "Kein gueltiges Muster gefunden - Notfalldaten aktiv")
        if not cups:
            cups = _builtin_cups()
            builtin.append(CUPS_FILE)
            self._reporter.warning("config", "Kein gueltiger Saugertyp gefunden - Notfalldaten aktiv")

        status = ConfigStatus(
            directory=self._directory,
            pallet_count=len(pallets),
            pattern_count=len(patterns),
            cup_count=len(cups),
            failed_files=tuple(failed),
            used_builtin=tuple(builtin),
        )

        with self._lock:
            self._pallets = pallets
            self._patterns = patterns
            self._cups = cups
            self._vacuum = vacuum
            self._status = status

        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception as exc:
                self._reporter.exception(exc, source="config")

        return status

    def _check_version(self, filename: str, data: dict) -> None:
        version = data.get("version")
        if version is None:
            return
        try:
            value = int(version)
        except (TypeError, ValueError):
            self._reporter.warning("config", filename + ": Feld 'version' ist keine Zahl")
            return
        if value > CONFIG_VERSION:
            self._reporter.warning(
                "config",
                filename + " hat Version " + str(value) + ", erwartet wird hoechstens "
                + str(CONFIG_VERSION) + " - neuere Felder werden ignoriert",
            )

    def add_listener(self, callback) -> None:
        """Rueckruf nach jedem Neuladen. Bewusst ohne Qt, damit auch Engines
        und Jobs zuhoeren koennen."""
        self._listeners.append(callback)

    # Abfragen -----------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._directory

    def status(self) -> ConfigStatus | None:
        with self._lock:
            return self._status

    def get_pallets(self) -> tuple[PalletSpec, ...]:
        with self._lock:
            return self._pallets

    def get_pallet(self, pallet_id: str) -> PalletSpec | None:
        return next((p for p in self.get_pallets() if p.id == pallet_id), None)

    def get_patterns(self) -> tuple[PatternSpec, ...]:
        with self._lock:
            return self._patterns

    def get_pattern(self, pattern_id: str) -> PatternSpec | None:
        return next((p for p in self.get_patterns() if p.id == pattern_id), None)

    def get_suction_cups(self) -> tuple[SuctionCupSpec, ...]:
        with self._lock:
            return self._cups

    def get_suction_cup(self, cup_id: str) -> SuctionCupSpec | None:
        return next((c for c in self.get_suction_cups() if c.id == cup_id), None)

    def get_vacuum_defaults(self) -> VacuumDefaults:
        with self._lock:
            if self._vacuum is None:
                from app.domain.catalog import VacuumDefaults as VD
                from app.vacuum.models import RestrictorSpec
                from app.vacuum.models import LeakageSpec

                return VD(
                    plate=VacuumPlateSpec(800.0, 600.0), pump=PumpSpec(),
                    restrictor=RestrictorSpec(), leakage=LeakageSpec(),
                )
            return self._vacuum

    def default_suction_cup(self) -> SuctionCupSpec | None:
        wanted = self.get_vacuum_defaults().default_cup_id
        return self.get_suction_cup(wanted) or (self.get_suction_cups()[0] if self.get_suction_cups() else None)
