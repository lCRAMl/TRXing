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

from __future__ import annotations

from typing import Protocol

from app.core.units import lpm_to_m3s
from app.dto.vacuum import LeakageModel, LeakageSpec


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
