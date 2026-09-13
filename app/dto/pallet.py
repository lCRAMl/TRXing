"""Datenobjekte der Palettierung.

Die Hoehenangaben brauchen eine klare Abgrenzung, sonst rechnet jeder Teil des
Programms mit einer anderen Bezugsebene:

    deck_height_mm      Bauhoehe der leeren Palette
    max_load_height_mm  zulaessige Hoehe des Stapels UEBER dem Deck
    total_height_mm     Deck plus Stapel - der Wert, der ins Regal passen muss

Alle Platzierungskoordinaten beziehen sich auf die Deckflaeche der Palette,
z_mm = 0 ist also die Oberkante des Decks und nicht der Boden.

Ueberstand und Randabstand sind bewusst getrennt: ein negativer Rand (Karton
darf ueberstehen) und ein Sicherheitsabstand nach innen sind zwei verschiedene
betriebliche Vorgaben, die auch gemeinsam auftreten koennen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.trace import FrozenTrace
from app.dto.common import CalculationMeta
from app.dto.package import Orientation, PackageSpec


@dataclass(frozen=True, slots=True)
class PalletSpec:
    """Ein Palettentyp aus config/pallets.json."""

    id: str
    name: str
    length_mm: float
    width_mm: float
    max_load_kg: float
    max_load_height_mm: float
    deck_height_mm: float = 144.0
    tare_weight_kg: float = 0.0

    #: Zulaessiger Ueberstand des Ladeguts ueber die Palettenkante, je Seite.
    overhang_mm: float = 0.0

    #: Sicherheitsabstand nach innen, je Seite. Wirkt der Ueberstandsfreigabe
    #: entgegen und wird mit ihr verrechnet.
    edge_clearance_mm: float = 0.0

    @property
    def footprint_area_mm2(self) -> float:
        return self.length_mm * self.width_mm

    @property
    def usable_length_mm(self) -> float:
        return self.length_mm + 2.0 * (self.overhang_mm - self.edge_clearance_mm)

    @property
    def usable_width_mm(self) -> float:
        return self.width_mm + 2.0 * (self.overhang_mm - self.edge_clearance_mm)

    @property
    def usable_area_mm2(self) -> float:
        return max(0.0, self.usable_length_mm) * max(0.0, self.usable_width_mm)


class ZMode(Enum):
    """Verhaeltnis aufeinanderfolgender Lagen zueinander."""

    IDENTICAL = "identical"
    MIRROR = "mirror"
    ROTATE90 = "rotate90"

    @property
    def label(self) -> str:
        return {
            ZMode.IDENTICAL: "Lagen gleich (Saeule)",
            ZMode.MIRROR: "Lagen gespiegelt (Verband)",
            ZMode.ROTATE90: "Lagen um 90 Grad gedreht",
        }[self]


@dataclass(frozen=True, slots=True)
class PatternSpec:
    """Ein Palettiermuster aus config/pallet_patterns.json.

    strategy benennt die Ebenen-Strategie, die die Engine dafuer aufruft;
    z_mode beschreibt die Fortsetzung nach oben. Die Trennung erlaubt es,
    dieselbe Grundflaeche mit verschiedenen Stapelarten zu kombinieren, ohne
    fuer jede Kombination eine eigene Klasse zu schreiben.
    """

    id: str
    name: str
    strategy: str
    z_mode: ZMode = ZMode.MIRROR
    description: str = ""
    options: dict = field(default_factory=dict)

    #: Wenn gesetzt, beschraenkt sich das Muster auf Pakete in diesem Bereich.
    min_package_edge_mm: float = 0.0
    max_package_edge_mm: float = 0.0


@dataclass(frozen=True, slots=True)
class PalletConstraints:
    """Randbedingungen eines Optimierungslaufs.

    Die Werte stammen teils aus dem Palettentyp, teils aus der Eingabe des
    Benutzers. Sie werden hier zusammengefuehrt, damit die Engine genau eine
    Quelle hat und nicht selbst entscheiden muss, welcher Wert gewinnt.
    """

    max_height_mm: float
    max_load_kg: float
    max_stack_load_kg: float = 0.0
    desired_count: int = 0
    gap_mm: float = 0.0
    include_deck_in_height: bool = True
    allow_tipping: bool = False
    use_solver: bool = False

    @property
    def has_stack_load_limit(self) -> bool:
        return self.max_stack_load_kg > 0.0


@dataclass(frozen=True, slots=True)
class Placement:
    """Ein platziertes Paket. Rein geometrisch, ohne Qt und ohne Bewertung."""

    package_index: int
    layer_index: int
    x_mm: float
    y_mm: float
    z_mm: float
    length_mm: float
    width_mm: float
    height_mm: float
    rotated: bool = False
    orientation: Orientation = Orientation.UPRIGHT
    weight_kg: float = 0.0

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.length_mm

    @property
    def top_mm(self) -> float:
        return self.y_mm + self.width_mm

    @property
    def footprint_area_mm2(self) -> float:
        return self.length_mm * self.width_mm

    def overlap_area_mm2(self, other: Placement) -> float:
        """Ueberdeckung der Standflaechen zweier Platzierungen."""
        dx = min(self.right_mm, other.right_mm) - max(self.x_mm, other.x_mm)
        dy = min(self.top_mm, other.top_mm) - max(self.y_mm, other.y_mm)
        return dx * dy if dx > 0 and dy > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Layer:
    """Eine Lage der Palette."""

    index: int
    z_mm: float
    height_mm: float
    placements: tuple[Placement, ...] = ()
    variant: str = ""
    footprint_utilization_ratio: float = 0.0

    @property
    def count(self) -> int:
        return len(self.placements)

    @property
    def weight_kg(self) -> float:
        return sum(p.weight_kg for p in self.placements)


class LoadStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def label(self) -> str:
        return {LoadStatus.OK: "In Ordnung", LoadStatus.WARNING: "Grenzwertig", LoadStatus.CRITICAL: "Ueberlastet"}[self]


@dataclass(frozen=True, slots=True)
class PackageLoad:
    """Auflast auf einem einzelnen Paket im Stapel."""

    package_index: int
    layer_index: int
    supported_weight_kg: float
    max_stack_load_kg: float
    load_pct: float
    status: LoadStatus = LoadStatus.OK


@dataclass(frozen=True, slots=True)
class LoadAnalysis:
    """Ergebnis der Lastweitergabe durch den Stapel."""

    per_package: tuple[PackageLoad, ...] = ()
    max_load_pct: float = 0.0
    critical_count: int = 0
    warning_count: int = 0
    checked: bool = True


class LimitingFactor(Enum):
    """Was die Stapelhoehe tatsaechlich begrenzt hat - die Angabe, nach der
    der Benutzer als erstes sucht, wenn weniger Pakete herauskommen als
    erwartet."""

    HEIGHT = "height"
    PALLET_LOAD = "pallet_load"
    PACKAGE_LOAD = "package_load"
    DESIRED_COUNT = "desired_count"
    NONE = "none"

    @property
    def label(self) -> str:
        return {
            LimitingFactor.HEIGHT: "Maximale Palettenhoehe",
            LimitingFactor.PALLET_LOAD: "Maximale Palettenlast",
            LimitingFactor.PACKAGE_LOAD: "Zulaessige Stapellast des Pakets",
            LimitingFactor.DESIRED_COUNT: "Gewuenschte Stueckzahl",
            LimitingFactor.NONE: "Keine Begrenzung erreicht",
        }[self]


@dataclass(frozen=True, slots=True)
class PalletResult:
    """Vollstaendiges Ergebnis eines Palettierlaufs. Enthaelt nur Daten."""

    meta: CalculationMeta
    pallet: PalletSpec
    package: PackageSpec
    pattern_id: str
    pattern_name: str
    layers: tuple[Layer, ...] = ()
    total_count: int = 0
    per_layer_count: int = 0
    layer_count: int = 0
    total_load_height_mm: float = 0.0
    total_height_mm: float = 0.0
    total_weight_kg: float = 0.0
    used_area_mm2: float = 0.0
    footprint_utilization_ratio: float = 0.0
    volume_utilization_ratio: float = 0.0
    load: LoadAnalysis = field(default_factory=LoadAnalysis)
    limiting_factor: LimitingFactor = LimitingFactor.NONE
    warnings: tuple[str, ...] = ()
    trace: FrozenTrace | None = None

    @property
    def base_layer(self) -> Layer | None:
        return self.layers[0] if self.layers else None

    def layer(self, index: int) -> Layer | None:
        for entry in self.layers:
            if entry.index == index:
                return entry
        return None
