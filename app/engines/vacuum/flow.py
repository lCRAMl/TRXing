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

from __future__ import annotations

import math

from app.core.units import (
    AIR_DENSITY_KGM3,
    AIR_GAS_CONSTANT,
    AIR_KAPPA,
    STANDARD_TEMPERATURE_K,
)
from app.dto.suction import RestrictorMode, RestrictorSpec, SuctionCupSpec
from app.dto.vacuum import PumpSpec

#: Kritisches Druckverhaeltnis fuer Luft: unterhalb davon ist die Stroemung
#: durch die Blende gesperrt und der Massenstrom vom Gegendruck unabhaengig.
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
