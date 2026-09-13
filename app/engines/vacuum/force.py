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

from __future__ import annotations

from dataclasses import dataclass

from app.core.units import GRAVITY_MS2
from app.dto.suction import SuctionCupSpec
from app.dto.vacuum import GripDirection

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
