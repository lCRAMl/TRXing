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

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app.config.loader import ConfigLoader
from app.config.schema import (
    CONFIG_VERSION,
    VacuumDefaults,
    parse_pallets,
    parse_patterns,
    parse_suction_cups,
    parse_vacuum_defaults,
)
from app.core.errors import ErrorReporter
from app.dto.pallet import PalletSpec, PatternSpec, ZMode
from app.dto.suction import SuctionCupSpec
from app.dto.vacuum import PumpSpec, VacuumPlateSpec

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
                from app.config.schema import VacuumDefaults as VD
                from app.dto.suction import RestrictorSpec
                from app.dto.vacuum import LeakageSpec

                return VD(
                    plate=VacuumPlateSpec(800.0, 600.0), pump=PumpSpec(),
                    restrictor=RestrictorSpec(), leakage=LeakageSpec(),
                )
            return self._vacuum

    def default_suction_cup(self) -> SuctionCupSpec | None:
        wanted = self.get_vacuum_defaults().default_cup_id
        return self.get_suction_cup(wanted) or (self.get_suction_cups()[0] if self.get_suction_cups() else None)
