"""Datenobjekte der Vakuumplatte.

Zum Vorzeichen: Unterdruck wird durchgaengig als positive Druckdifferenz zur
Umgebung gefuehrt (vacuum_pa). Die im Datenblatt uebliche Schreibweise -0,6 bar
entspricht hier 60000 Pa. Siehe app/core/units.py.

Zum Arbeitspunkt: die Anwendung rechnet nicht mit dem eingestellten Sollvakuum,
sondern loest den Schnittpunkt aus Pumpenkennlinie und Leckagebedarf. Ein
offener Sauger senkt damit das erreichbare Vakuum und dadurch die Haltekraft -
statt nur eine Warnung zu erzeugen, waehrend das Ergebnis weiter mit dem
Sollvakuum glaenzt. Das Sollvakuum bleibt als Vergleichswert erhalten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.result import Status
from app.core.trace import FrozenTrace
from app.core.units import GRAVITY_MS2, STANDARD_AMBIENT_PA
from app.dto.common import CalculationMeta
from app.dto.package import PackageSpec
from app.dto.suction import ContactClass, CupContact, RestrictorSpec, SuctionCupSpec, SuctionPlacement


@dataclass(frozen=True, slots=True)
class VacuumPlateSpec:
    """Geometrie der Saugerplatte."""

    length_mm: float
    width_mm: float
    thickness_mm: float = 15.0

    #: Abstand der aeussersten Saugermitten zum Plattenrand.
    edge_margin_mm: float = 20.0

    #: Lichter Mindestabstand zwischen zwei Saugeraussenkanten.
    min_spacing_mm: float = 5.0

    @property
    def area_mm2(self) -> float:
        return self.length_mm * self.width_mm


class LeakageModel(Enum):
    """Modelltyp fuer den Luftdurchtritt durch den Karton.

    Die Permeabilitaet ist keine Naturkonstante und wird hier auch nicht als
    solche behandelt (Spezifikation 22): der Benutzer gibt sie vor, das Modell
    bestimmt nur, wie daraus ein Volumenstrom wird.

    NONE            dichter Karton, kein Durchtritt
    CONSTANT        fester Strom je wirksamem Sauger, unabhaengig vom Druck
    FLOW_PER_AREA   Strom je wirksamer Flaeche bei Bezugsdruck, ueber das
                    Druckverhaeltnis mit dem Exponenten skaliert
    PRESSURE_LINEAR Strom proportional zu Flaeche und Druckdifferenz (Darcy)
    """

    NONE = "none"
    CONSTANT = "constant"
    FLOW_PER_AREA = "flow_per_area"
    PRESSURE_LINEAR = "pressure_linear"

    @property
    def label(self) -> str:
        return {
            LeakageModel.NONE: "Dicht (kein Durchtritt)",
            LeakageModel.CONSTANT: "Konstanter Strom je Sauger",
            LeakageModel.FLOW_PER_AREA: "Strom je Flaeche bei Bezugsdruck",
            LeakageModel.PRESSURE_LINEAR: "Druckproportional (Darcy)",
        }[self]


@dataclass(frozen=True, slots=True)
class LeakageSpec:
    """Parameter des gewaehlten Permeabilitaetsmodells.

    permeability_value wird je nach Modell verschieden gelesen; unit_label sagt,
    wie. Die Oberflaeche zeigt beides an, damit aus der Zahl allein kein
    scheinbar exakter Kennwert wird.
    """

    model: LeakageModel = LeakageModel.NONE
    permeability_value: float = 0.0
    unit_label: str = ""
    reference_vacuum_pa: float = 60000.0

    #: Exponent der Druckskalierung bei FLOW_PER_AREA. 1,0 ist laminar,
    #: 0,5 turbulent. Modellannahme, kein Messwert.
    pressure_exponent_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class PumpSpec:
    """Vakuumerzeuger.

    Zwei Betriebsarten: entweder ein Nennstrom bei einem Bezugsvakuum, oder
    eine Kennlinie aus Stuetzpunkten. Reale Ejektoren liefern bei hohem Vakuum
    deutlich weniger Strom als im Leerlauf; ohne Kennlinie ist der Arbeitspunkt
    nur eine grobe Naeherung, was im Trace vermerkt wird.
    """

    name: str = "Vakuumerzeuger"
    nominal_flow_m3s: float = 0.0
    max_vacuum_pa: float = 85000.0

    #: Stuetzpunkte (vacuum_pa, flow_m3s), aufsteigend nach Vakuum. Leer
    #: bedeutet: lineare Naeherung von nominal_flow bei 0 Pa auf 0 bei
    #: max_vacuum_pa.
    curve_points: tuple[tuple[float, float], ...] = ()


class GripDirection(Enum):
    """Lage der Ansaugflaeche.

    HORIZONTAL Platte greift von oben, das Vakuum traegt die Last unmittelbar.
    VERTICAL   Platte greift seitlich, die Last haengt an der Reibung zwischen
               Sauger und Karton. Der Reibbeiwert ist eine Benutzerangabe und
               steht in keinem Datenblatt.
    """

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"

    @property
    def label(self) -> str:
        return {
            GripDirection.HORIZONTAL: "Von oben (Vakuum traegt direkt)",
            GripDirection.VERTICAL: "Seitlich (Last haengt an der Reibung)",
        }[self]


@dataclass(frozen=True, slots=True)
class VacuumInput:
    """Vollstaendige Eingabe eines Vakuumlaufs."""

    package: PackageSpec
    plate: VacuumPlateSpec
    cup: SuctionCupSpec

    #: 0 bedeutet: automatisch maximal bestuecken.
    requested_cup_count: int = 0
    package_count: int = 1

    #: Muster der Paketanordnung unter der Platte (aus der Palettierung).
    pattern_id: str = ""

    #: Muster, nach dem die Sauger auf der Platte sitzen. Siehe
    #: app/engines/vacuum/arrangements.py.
    arrangement_id: str = "grid_spread"

    target_vacuum_pa: float = 60000.0
    ambient_pa: float = STANDARD_AMBIENT_PA
    pump: PumpSpec = field(default_factory=PumpSpec)
    leakage: LeakageSpec = field(default_factory=LeakageSpec)
    restrictor: RestrictorSpec = field(default_factory=RestrictorSpec)

    safety_factor: float = 2.0
    acceleration_ms2: float = 0.0
    gravity_ms2: float = GRAVITY_MS2
    grip: GripDirection = GripDirection.HORIZONTAL

    #: Reibbeiwert Sauger gegen Karton. Nur bei seitlichem Griff wirksam.
    friction_factor: float = 0.5

    #: Ob teilweise aufliegende Sauger als tragend gezaehlt werden. Aus gutem
    #: Grund aus: eine unterbrochene Dichtlippe traegt nicht.
    count_partial_as_sealed: bool = False

    #: Rechnet den Arbeitspunkt statt mit dem Sollvakuum zu rechnen.
    solve_operating_point: bool = True


@dataclass(frozen=True, slots=True)
class FlowBreakdown:
    """Aufteilung des Volumenstroms am Arbeitspunkt."""

    open_cups_m3s: float = 0.0
    partial_cups_m3s: float = 0.0
    workpiece_m3s: float = 0.0
    total_required_m3s: float = 0.0
    available_m3s: float = 0.0

    @property
    def leak_m3s(self) -> float:
        return self.open_cups_m3s + self.partial_cups_m3s

    @property
    def remaining_m3s(self) -> float:
        return self.available_m3s - self.total_required_m3s


@dataclass(frozen=True, slots=True)
class ForceBreakdown:
    """Kraefte am Arbeitspunkt."""

    theoretical_per_cup_n: float = 0.0
    total_holding_n: float = 0.0
    required_n: float = 0.0
    cup_limit_n: float = 0.0
    limited_by_cup_strength: bool = False


@dataclass(frozen=True, slots=True)
class VacuumResult:
    """Ergebnis eines Vakuumlaufs. Enthaelt nur Daten."""

    meta: CalculationMeta
    plate: VacuumPlateSpec
    cup: SuctionCupSpec
    placements: tuple[SuctionPlacement, ...] = ()
    contacts: tuple[CupContact, ...] = ()
    package_rects: tuple[tuple[float, float, float, float], ...] = ()

    arrangement_id: str = ""

    #: Mittenabstand benachbarter Sauger. Das Rastermass ist Aussenmass plus
    #: lichtem Mindestabstand - die Anzeige rechnet es nicht nach, sie zeigt
    #: es (Spezifikation 37).
    pitch_x_mm: float = 0.0
    pitch_y_mm: float = 0.0

    total_cup_count: int = 0
    sealed_count: int = 0
    partial_count: int = 0
    open_count: int = 0
    max_cup_count: int = 0

    effective_area_mm2: float = 0.0
    target_vacuum_pa: float = 0.0
    achieved_vacuum_pa: float = 0.0

    flow: FlowBreakdown = field(default_factory=FlowBreakdown)
    force: ForceBreakdown = field(default_factory=ForceBreakdown)

    max_package_mass_kg: float = 0.0
    actual_mass_kg: float = 0.0
    required_cup_count: int = 0
    status: Status = Status.INSUFFICIENT
    warnings: tuple[str, ...] = ()
    trace: FrozenTrace | None = None

    def contact_of(self, placement_index: int) -> CupContact | None:
        for entry in self.contacts:
            if entry.placement_index == placement_index:
                return entry
        return None

    def indices_with(self, contact: ContactClass) -> tuple[int, ...]:
        return tuple(c.placement_index for c in self.contacts if c.contact is contact)
