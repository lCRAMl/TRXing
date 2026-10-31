"""Die Physik der Saugplatte.

Vier Fragen, die nacheinander beantwortet werden und deshalb zusammengehoeren:

    force     welche Kraft ein Sauger bei gegebenem Vakuum aufbringt
    contact   welcher Sauger ueberhaupt dicht auf einem Karton liegt
    leakage   wieviel Luft durch den Karton selbst nachstroemt
    flow      welcher Volumenstrom insgesamt gebraucht wird und was die
              Pumpe am Arbeitspunkt liefert

Die Reihenfolge in dieser Datei folgt der Abhaengigkeit: contact braucht die
wirksame Flaeche aus force, flow braucht beide.

Zusammengelegt aus engines/vacuum/{force,contact,leakage,flow}.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from app.domain.units import GRAVITY_MS2
from app.vacuum.models import SuctionCupSpec
from app.vacuum.models import GripDirection
from app.domain.geometry import Footprint
from app.vacuum.models import ContactClass, CupContact, SuctionCupSpec, SuctionPlacement
from app.domain.geometry import circle_fits_in_rect, circle_rect_overlap_area_mm2
from typing import Protocol
from app.domain.units import lpm_to_m3s
from app.vacuum.models import LeakageModel, LeakageSpec
import math
from app.domain.units import (
    AIR_DENSITY_KGM3,
    AIR_GAS_CONSTANT,
    AIR_KAPPA,
    STANDARD_TEMPERATURE_K,
)
from app.vacuum.models import RestrictorMode, RestrictorSpec, SuctionCupSpec
from app.vacuum.models import PumpSpec


# ---------------------------------------------------------------------------
# force.py
# ---------------------------------------------------------------------------
"""Kraftmodell der Saugerplatte.

Die entscheidende Frage ist, welche Flaeche mit der Druckdifferenz zu
multiplizieren ist. Spezifikation 20 sagt dazu: die theoretischen
Herstellerkraefte duerfen als Referenz dienen, muessen aber nicht blind mit der
geometrischen Flaeche multipliziert werden.

Der Abgleich der Datenblattwerte mit der Geometrie loest das ohne jede Annahme.
Die Kreisflaeche des inneren Faltendurchmessers d2 mal 60000 Pa ergibt genau die
angegebene Saugkraft:

    SPB2 20   d2 12,0 mm  ->  6,79 N   Datenblatt  6,8 N   (-0,2 %)
    SPB2 25   d2 14,5 mm  ->  9,91 N   Datenblatt  9,9 N   (+0,1 %)
    SPB2 30   d2 16,9 mm  -> 13,46 N   Datenblatt 14,4 N   (-6,5 %)
    SPB2 40   d2 22,9 mm  -> 24,71 N   Datenblatt 24,8 N   (-0,4 %)
    SPB2 50   d2 27,1 mm  -> 34,61 N   Datenblatt 34,6 N   (+0,0 %)

Vier von fuenf Groessen stimmen auf unter einem Prozent. Damit ist die wirksame
Flaeche keine Erfindung dieses Programms, sondern aus dem Datenblatt abgeleitet.

Gerechnet wird trotzdem mit der aus der DATENBLATTKRAFT zurueckgerechneten
Flaeche, nicht mit der aus d2. Zwei Gruende: bei -0,6 bar kommt exakt der
Herstellerwert heraus, und die einzige Groesse mit Abweichung (SPB2 30) wird
nicht stillschweigend um 6,5 Prozent nach unten korrigiert. Die Abweichung wird
stattdessen ausgewiesen.

Zwei Grenzen begrenzen die Kraft zusaetzlich, beide aus dem Datenblatt:

    Abreisskraft   mechanische Grenze des Saugers selbst
    Querkraft      Grenze bei seitlicher Belastung

Bei -0,6 bar liegt die Saugkraft unter beiden. Bei hoeherem Unterdruck kann die
Abreisskraft zur bindenden Grenze werden - dann ist nicht mehr das Vakuum das
Problem, sondern der Sauger.
"""

def datasheet_effective_area_mm2(cup: SuctionCupSpec) -> float:
    """Wirksame Flaeche, aus der Datenblattkraft zurueckgerechnet.

    A = F / dp_ref, mit dem Bezugsdruck des jeweiligen Datenblatts. Beim
    Bezugsdruck liefert sie exakt den Herstellerwert, bei anderem Unterdruck
    skaliert sie physikalisch richtig.

    Der Bezugsdruck steht am Saugertyp und nicht als Konstante im Code: Schmalz
    nennt -0,6 bar, andere Hersteller beziehen auf -0,7 oder -0,8 bar. Eine
    feste Konstante wuerde deren Werte stillschweigend verfaelschen.
    """
    return cup.datasheet_area_mm2


def holding_force_per_cup_n(cup: SuctionCupSpec, vacuum_pa: float) -> float:
    """Haltekraft eines dichtenden Saugers beim gegebenen Unterdruck.

    Auf die Abreisskraft begrenzt: mehr Vakuum bringt keine Kraft mehr, wenn
    der Sauger vorher abreisst.
    """
    force = vacuum_pa * datasheet_effective_area_mm2(cup) / 1_000_000.0
    if cup.pull_off_force_n > 0.0:
        return min(force, cup.pull_off_force_n)
    return force


def cup_force_limit_n(cup: SuctionCupSpec, grip: GripDirection) -> float:
    """Mechanische Grenze eines Saugers in dieser Griffrichtung.

    Beim Griff von oben ist die Abreisskraft massgeblich, beim seitlichen Griff
    zusaetzlich die Querkraft. Null bedeutet: das Datenblatt nennt keinen Wert.
    """
    if grip is GripDirection.VERTICAL and cup.lateral_force_n > 0.0:
        return cup.lateral_force_n
    return cup.pull_off_force_n


@dataclass(frozen=True, slots=True)
class ForceResult:
    total_holding_n: float
    per_cup_n: float
    required_n: float
    max_mass_kg: float
    cup_limit_n: float
    limited_by_cup_strength: bool


def required_force_n(
    mass_kg: float,
    safety_factor: float,
    acceleration_ms2: float = 0.0,
    gravity_ms2: float = GRAVITY_MS2,
    grip: GripDirection = GripDirection.HORIZONTAL,
    friction_factor: float = 0.5,
) -> float:
    """Kraft, die die Platte aufbringen muss.

    Beim Griff von oben traegt das Vakuum die Last unmittelbar:

        F = m * (g + a) * S

    Beim seitlichen Griff haengt die Last an der Reibung zwischen Sauger und
    Karton; die Normalkraft muss um den Kehrwert des Reibbeiwerts groesser sein:

        F = m * (g + a) * S / mu

    Die Beschleunigung a steht standardmaessig auf null, das Ergebnis ist dann
    die rein statische Rechnung. Wer die Beschleunigung seines Portals oder
    Roboters eintraegt, bekommt den realistischen Wert - beim Palettieren ist
    der Unterschied betraechtlich.

    Der Reibbeiwert ist eine Benutzerangabe und steht in keinem Datenblatt.
    """
    demand = mass_kg * (gravity_ms2 + max(0.0, acceleration_ms2)) * max(1.0, safety_factor)
    if grip is GripDirection.VERTICAL:
        if friction_factor <= 0.0:
            return float("inf")
        return demand / friction_factor
    return demand


def max_mass_kg(
    total_holding_n: float,
    safety_factor: float,
    acceleration_ms2: float = 0.0,
    gravity_ms2: float = GRAVITY_MS2,
    grip: GripDirection = GripDirection.HORIZONTAL,
    friction_factor: float = 0.5,
) -> float:
    """Umkehrung von required_force_n - die Rueckwaertsfrage aus Spezifikation 24."""
    denominator = (gravity_ms2 + max(0.0, acceleration_ms2)) * max(1.0, safety_factor)
    if denominator <= 0.0 or total_holding_n <= 0.0:
        return 0.0
    usable = total_holding_n * friction_factor if grip is GripDirection.VERTICAL else total_holding_n
    return usable / denominator


def required_cup_count(
    mass_kg: float,
    cup: SuctionCupSpec,
    vacuum_pa: float,
    safety_factor: float,
    acceleration_ms2: float = 0.0,
    gravity_ms2: float = GRAVITY_MS2,
    grip: GripDirection = GripDirection.HORIZONTAL,
    friction_factor: float = 0.5,
) -> int:
    """Wie viele wirksame Sauger dieses Gewicht braucht (Spezifikation 24).

    Aufgerundet - ein halber Sauger traegt nichts.
    """
    per_cup = holding_force_per_cup_n(cup, vacuum_pa)
    if per_cup <= 0.0:
        return 0
    needed = required_force_n(mass_kg, safety_factor, acceleration_ms2, gravity_ms2, grip, friction_factor)
    if needed == float("inf"):
        return 0
    return int(-(-needed // per_cup))  # Aufrunden ohne Gleitkomma-Umweg


def evaluate(
    cup: SuctionCupSpec,
    sealed_count: int,
    vacuum_pa: float,
    mass_kg: float,
    safety_factor: float,
    acceleration_ms2: float = 0.0,
    gravity_ms2: float = GRAVITY_MS2,
    grip: GripDirection = GripDirection.HORIZONTAL,
    friction_factor: float = 0.5,
) -> ForceResult:
    """Vollstaendige Kraftbilanz der Platte."""
    theoretical = vacuum_pa * datasheet_effective_area_mm2(cup) / 1_000_000.0
    limit = cup_force_limit_n(cup, grip)
    limited = limit > 0.0 and theoretical > limit
    per_cup = min(theoretical, limit) if limit > 0.0 else theoretical

    total = per_cup * max(0, sealed_count)
    return ForceResult(
        total_holding_n=total,
        per_cup_n=per_cup,
        required_n=required_force_n(mass_kg, safety_factor, acceleration_ms2, gravity_ms2, grip, friction_factor),
        max_mass_kg=max_mass_kg(total, safety_factor, acceleration_ms2, gravity_ms2, grip, friction_factor),
        cup_limit_n=limit,
        limited_by_cup_strength=limited,
    )


# ---------------------------------------------------------------------------
# contact.py
# ---------------------------------------------------------------------------
"""Welche Sauger liegen tatsaechlich auf einem Karton.

Spezifikation 19 ist hier ausdruecklich: keine reine Zaehlung nach Mittelpunkt.
Ein Sauger, dessen Mitte gerade noch ueber der Kartonkante liegt, traegt nichts -
er zieht Fremdluft.

Das physikalische Kriterium ist nicht die ueberdeckte Flaeche, sondern der
Dichtlippenring: nur wenn der Ring (Durchmesser Ds aus dem Datenblatt)
vollstaendig auf der Kartonflaeche aufliegt, entsteht ein geschlossener Raum.
Ist der Ring an einer Stelle unterbrochen, stroemt dort Luft nach - der Sauger
verhaelt sich dann wie ein offener, auch wenn er zu 95 Prozent aufliegt.

Daraus ergeben sich die drei geforderten Klassen:

    SEALED   Dichtlippenring ganz auf dem Karton        - traegt
    PARTIAL  Ring teilweise auf dem Karton              - traegt nicht, leckt
    OPEN     kein Karton unter dem Sauger               - traegt nicht, leckt

PARTIAL bleibt trotz gleicher Physik eine eigene Klasse, weil die Unterscheidung
dem Benutzer etwas sagt: ein teilweise aufliegender Sauger ist ein Hinweis, dass
ein anderes Raster oder eine andere Plattengroesse das Problem loest. Ein
offener Sauger mitten ueber einer Luecke ist ein anderer Befund.

Ueber count_partial_as_sealed laesst sich das Verhalten umstellen - etwa fuer
Sauger mit besonders nachgiebiger Dichtlippe. Standardmaessig aus, weil die
optimistische Annahme hier zu einem zu schweren Paket fuehren wuerde.

Die ueberdeckte Flaeche wird trotzdem exakt berechnet (geschlossene Loesung in
app/domain/geometry.py) und ausgegeben - sie ist die Kennzahl, an der
man sieht, wie knapp ein Sauger daneben liegt.
"""

@dataclass(frozen=True, slots=True)
class ContactSummary:
    """Auswertung aller Sauger einer Platte."""

    contacts: tuple[CupContact, ...] = ()
    sealed_count: int = 0
    partial_count: int = 0
    open_count: int = 0
    effective_area_mm2: float = 0.0

    @property
    def total_count(self) -> int:
        return len(self.contacts)

    @property
    def leaking_count(self) -> int:
        """Sauger, die Fremdluft ziehen - offene und teilweise aufliegende."""
        return self.open_count + self.partial_count


def classify(
    placements: tuple[SuctionPlacement, ...],
    packages: tuple[Footprint, ...],
    cup: SuctionCupSpec,
    count_partial_as_sealed: bool = False,
) -> ContactSummary:
    """Ordnet jeden Sauger einer Kontaktklasse zu."""
    radius = cup.sealing_lip_diameter_mm / 2.0
    sealing_area = cup.sealing_area_mm2
    effective_per_cup = datasheet_effective_area_mm2(cup)

    contacts: list[CupContact] = []
    sealed = partial = open_count = 0
    effective_area = 0.0

    for placement in placements:
        if not placement.active:
            continue

        covered = 0.0
        fully_on: int = -1
        touching: int = -1
        for index, package in enumerate(packages):
            if circle_fits_in_rect(
                placement.center_x_mm, placement.center_y_mm, radius,
                package.x_mm, package.y_mm, package.length_mm, package.width_mm,
            ):
                fully_on = index
                covered = sealing_area
                break
            area = circle_rect_overlap_area_mm2(
                placement.center_x_mm, placement.center_y_mm, radius,
                package.x_mm, package.y_mm, package.length_mm, package.width_mm,
            )
            if area > 0.0:
                covered += area
                if touching < 0:
                    touching = index

        if fully_on >= 0:
            contact = ContactClass.SEALED
            package_index = fully_on
        elif covered > 0.0:
            # Beruehrt mehrere Kartons oder ragt ueber eine Kante: in beiden
            # Faellen ist der Dichtlippenring unterbrochen.
            contact = ContactClass.PARTIAL
            package_index = touching
        else:
            contact = ContactClass.OPEN
            package_index = -1

        counts_as_sealed = contact is ContactClass.SEALED or (
            contact is ContactClass.PARTIAL and count_partial_as_sealed
        )
        if counts_as_sealed:
            # Bei teilweiser Auflage wird die wirksame Flaeche im Verhaeltnis
            # der Ueberdeckung angesetzt - nur dann, wenn der Benutzer diese
            # optimistische Annahme ausdruecklich eingeschaltet hat.
            share = 1.0 if contact is ContactClass.SEALED else (
                covered / sealing_area if sealing_area > 0 else 0.0
            )
            cup_area = effective_per_cup * share
        else:
            cup_area = 0.0

        effective_area += cup_area
        if contact is ContactClass.SEALED:
            sealed += 1
        elif contact is ContactClass.PARTIAL:
            partial += 1
        else:
            open_count += 1

        contacts.append(
            CupContact(
                placement_index=placement.index,
                contact=contact,
                covered_area_mm2=covered,
                coverage_ratio=(covered / sealing_area) if sealing_area > 0 else 0.0,
                effective_area_mm2=cup_area,
                package_index=package_index,
            )
        )

    return ContactSummary(
        contacts=tuple(contacts),
        sealed_count=sealed,
        partial_count=partial,
        open_count=open_count,
        effective_area_mm2=effective_area,
    )


def bearing_count(summary: ContactSummary, count_partial_as_sealed: bool = False) -> int:
    """Anzahl der Sauger, die Kraft uebertragen."""
    if count_partial_as_sealed:
        return summary.sealed_count + summary.partial_count
    return summary.sealed_count


# ---------------------------------------------------------------------------
# leakage.py
# ---------------------------------------------------------------------------
"""Luftdurchtritt durch den Karton.

Spezifikation 22 ist an dieser Stelle ausdruecklich: die Permeabilitaet darf
nicht als erfundene Naturkonstante behandelt werden. Sie ist hier deshalb
durchgaengig eine Benutzerangabe, und dieses Modul entscheidet nur, wie aus
dieser Angabe ein Volumenstrom wird.

Vier Modelle, jedes mit einer eigenen Einheit fuer den eingegebenen Wert:

    NONE             dichte Oberflaeche, kein Durchtritt
    CONSTANT         l/min je wirksamem Sauger, druckunabhaengig
    FLOW_PER_AREA    l/min je cm2 beim Bezugsdruck, mit Exponent skaliert
    PRESSURE_LINEAR  l/min je cm2 und 1000 Pa (Darcy, druckproportional)

Welche Einheit gilt, steht in LeakageSpec.unit_label und wird in der Oberflaeche
neben dem Eingabefeld angezeigt. Ohne diese Angabe waere die Zahl bedeutungslos.

Eine Formel steht hier und nirgends sonst - insbesondere nicht im Tab
(Spezifikation 22).
"""

class LeakageCalculator(Protocol):
    """Vertrag eines Permeabilitaetsmodells."""

    def calculate_flow_m3s(
        self, spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int
    ) -> float: ...


class NoLeakage:
    """Dichte Oberflaeche."""

    def calculate_flow_m3s(self, spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int) -> float:
        return 0.0


class ConstantLeakage:
    """Fester Strom je wirksamem Sauger.

    Der einfachste brauchbare Ansatz, wenn aus einem Versuch bekannt ist, wieviel
    ein einzelner Sauger auf diesem Karton zieht. Druckunabhaengig - das ist die
    Vereinfachung dieses Modells und der Grund, es nur im Bereich des
    Messpunktes zu verwenden.
    """

    def calculate_flow_m3s(self, spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int) -> float:
        if vacuum_pa <= 0.0:
            return 0.0
        return lpm_to_m3s(spec.permeability_value) * max(0, cup_count)


class AreaLeakage:
    """Strom je wirksamer Flaeche, ueber das Druckverhaeltnis skaliert.

    Der Eingabewert gilt beim Bezugsdruck (Vorgabe -0,6 bar). Bei anderem
    Unterdruck wird mit (dp / dp_ref) hoch Exponent skaliert: 1,0 entspricht
    laminarem Durchtritt, 0,5 turbulentem. Der Exponent ist eine Modellannahme
    und keine Messgroesse.
    """

    def calculate_flow_m3s(self, spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int) -> float:
        if vacuum_pa <= 0.0 or area_mm2 <= 0.0 or spec.reference_vacuum_pa <= 0.0:
            return 0.0
        area_cm2 = area_mm2 / 100.0
        scale = (vacuum_pa / spec.reference_vacuum_pa) ** spec.pressure_exponent_factor
        return lpm_to_m3s(spec.permeability_value * area_cm2) * scale


class PressureLinearLeakage:
    """Druckproportionaler Durchtritt nach Darcy.

    Der Eingabewert gilt je cm2 und je 1000 Pa Druckdifferenz. Physikalisch die
    saubere Form fuer langsame Durchstroemung poroeser Schichten.
    """

    def calculate_flow_m3s(self, spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int) -> float:
        if vacuum_pa <= 0.0 or area_mm2 <= 0.0:
            return 0.0
        area_cm2 = area_mm2 / 100.0
        return lpm_to_m3s(spec.permeability_value * area_cm2 * vacuum_pa / 1000.0)


_MODELS: dict[LeakageModel, LeakageCalculator] = {
    LeakageModel.NONE: NoLeakage(),
    LeakageModel.CONSTANT: ConstantLeakage(),
    LeakageModel.FLOW_PER_AREA: AreaLeakage(),
    LeakageModel.PRESSURE_LINEAR: PressureLinearLeakage(),
}


def calculator_for(model: LeakageModel) -> LeakageCalculator:
    return _MODELS.get(model, _MODELS[LeakageModel.NONE])


def workpiece_flow_m3s(spec: LeakageSpec, vacuum_pa: float, area_mm2: float, cup_count: int) -> float:
    """Volumenstrom durch den Karton unter den wirksamen Saugern."""
    return calculator_for(spec.model).calculate_flow_m3s(spec, vacuum_pa, area_mm2, cup_count)


def describe(spec: LeakageSpec) -> str:
    """Einzeiler fuer Trace und Oberflaeche."""
    if spec.model is LeakageModel.NONE:
        return spec.model.label
    unit = (" " + spec.unit_label) if spec.unit_label else ""
    return spec.model.label + ": " + format(spec.permeability_value, "g") + unit


# ---------------------------------------------------------------------------
# flow.py
# ---------------------------------------------------------------------------
"""Luftstroeme: offene Sauger und Vakuumerzeuger.

Der Fremdluftstrom eines offenen Saugers ist in dieser Rechnung der groesste
einzelne Posten, und er ist auch der einzige, der sich ohne erfundene Kennwerte
aus dem Datenblatt herleiten laesst: das Datenblatt nennt die Bohrung dn des
Anschlusselements (4,0 mm bis 30 mm Sauger, 6,1 mm ab 40 mm), und durch diese
Bohrung stroemt Luft aus der Umgebung in die evakuierte Leitung.

Gerechnet wird als Stroemung durch eine Blende. Bei -0,6 bar ist das
Druckverhaeltnis 0,4 und liegt damit unter dem kritischen Verhaeltnis 0,528 -
die Stroemung ist gesperrt, der Massenstrom haengt nur noch vom Vordruck ab.
Beide Bereiche sind hier abgedeckt, damit auch kleine Unterdruecke stimmen.

Groessenordnung zur Einordnung (Cd = 0,8, 20 C, -0,6 bar):

    dn 4,0 mm  ->  rund  7 m3/h je offenem Sauger
    dn 6,1 mm  ->  rund 17 m3/h je offenem Sauger

Das uebersteigt die Leistung vieler Vakuumerzeuger. Ein einziger offener Sauger
kann das Vakuum der ganzen Platte zusammenbrechen lassen - deshalb sind
Strombegrenzer und Rueckschlagventile in der Praxis der Regelfall und hier
ausdruecklich modelliert.

Was NICHT aus dem Datenblatt stammt und deshalb Konfigurationswert ist: der
Ausflussbeiwert (Vorgabe 0,8, typisch fuer scharfkantige Bohrungen), die
Lufttemperatur und alle Angaben zum Strombegrenzer. Sie werden im Trace als
Annahme gefuehrt.
"""

CRITICAL_PRESSURE_RATIO = (2.0 / (AIR_KAPPA + 1.0)) ** (AIR_KAPPA / (AIR_KAPPA - 1.0))


def orifice_area_mm2(cup: SuctionCupSpec, restrictor: RestrictorSpec) -> float:
    """Engster Querschnitt zwischen Umgebung und Vakuumleitung.

    Ohne Begrenzer ist das die Bohrung des Anschlusselements. Ein Begrenzer
    verengt sie; ein Rueckschlagventil schliesst weitgehend, aber nie ganz -
    die Restleckage ist als Flaechenanteil modelliert.
    """
    bore = cup.bore_area_mm2
    if restrictor.mode is RestrictorMode.ORIFICE:
        radius = restrictor.diameter_mm / 2.0
        return min(bore, math.pi * radius * radius)
    if restrictor.mode is RestrictorMode.CHECK_VALVE:
        return bore * restrictor.check_valve_leak_ratio
    return bore


def orifice_flow_m3s(
    area_mm2: float,
    vacuum_pa: float,
    ambient_pa: float,
    discharge_coefficient_factor: float = 0.8,
    temperature_k: float = STANDARD_TEMPERATURE_K,
) -> float:
    """Volumenstrom durch eine Blende, bezogen auf Umgebungsdichte.

    Zurueckgegeben wird der Strom, den der Vakuumerzeuger abfuehren muss -
    gemessen in Kubikmetern Umgebungsluft je Sekunde. Das ist die Groesse, mit
    der Pumpenkennlinien ueblicherweise angegeben werden.
    """
    if area_mm2 <= 0.0 or vacuum_pa <= 0.0 or ambient_pa <= 0.0:
        return 0.0

    area_m2 = area_mm2 / 1_000_000.0
    downstream = max(0.0, ambient_pa - vacuum_pa)
    ratio = downstream / ambient_pa
    factor = discharge_coefficient_factor

    if ratio <= CRITICAL_PRESSURE_RATIO:
        # Gesperrte Stroemung: der Massenstrom haengt nur vom Vordruck ab.
        mass_flow = (
            factor * area_m2 * ambient_pa
            * math.sqrt(AIR_KAPPA / (AIR_GAS_CONSTANT * temperature_k))
            * (2.0 / (AIR_KAPPA + 1.0)) ** ((AIR_KAPPA + 1.0) / (2.0 * (AIR_KAPPA - 1.0)))
        )
    else:
        inner = (
            2.0 * AIR_KAPPA / ((AIR_KAPPA - 1.0) * AIR_GAS_CONSTANT * temperature_k)
            * (ratio ** (2.0 / AIR_KAPPA) - ratio ** ((AIR_KAPPA + 1.0) / AIR_KAPPA))
        )
        mass_flow = factor * area_m2 * ambient_pa * math.sqrt(max(0.0, inner))

    return mass_flow / AIR_DENSITY_KGM3


def open_cup_flow_m3s(
    cup: SuctionCupSpec,
    restrictor: RestrictorSpec,
    vacuum_pa: float,
    ambient_pa: float,
    temperature_k: float = STANDARD_TEMPERATURE_K,
) -> float:
    """Fremdluftstrom eines einzelnen offenen Saugers."""
    return orifice_flow_m3s(
        orifice_area_mm2(cup, restrictor),
        vacuum_pa,
        ambient_pa,
        restrictor.discharge_coefficient_factor,
        temperature_k,
    )


def pump_flow_m3s(pump: PumpSpec, vacuum_pa: float) -> float:
    """Verfuegbarer Volumenstrom des Erzeugers beim gegebenen Unterdruck.

    Mit Stuetzpunkten wird linear zwischen ihnen interpoliert, ausserhalb wird
    auf den Randwert begrenzt. Ohne Stuetzpunkte gilt eine Gerade vom Nennstrom
    bei null Unterdruck bis auf null beim Endvakuum. Die Gerade ist eine grobe
    Naeherung - reale Ejektoren knicken frueher ein. Sie wird im Trace als
    Annahme vermerkt, damit niemand sie fuer eine Herstellerkennlinie haelt.
    """
    if vacuum_pa <= 0.0:
        return pump.nominal_flow_m3s if not pump.curve_points else pump.curve_points[0][1]

    if pump.curve_points:
        points = pump.curve_points
        if vacuum_pa <= points[0][0]:
            return points[0][1]
        if vacuum_pa >= points[-1][0]:
            return points[-1][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= vacuum_pa <= x1:
                if x1 == x0:
                    return y1
                span = (vacuum_pa - x0) / (x1 - x0)
                return y0 + span * (y1 - y0)
        return points[-1][1]

    if pump.max_vacuum_pa <= 0.0:
        return 0.0
    if vacuum_pa >= pump.max_vacuum_pa:
        return 0.0
    return pump.nominal_flow_m3s * (1.0 - vacuum_pa / pump.max_vacuum_pa)
