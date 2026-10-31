"""Die einzige Autoritaet fuer Einheiten.

Warum es dieses Modul gibt: die Vakuumrechnung mischt Groessen, die in der
Praxis in voellig verschiedenen Einheiten notiert werden - Unterdruck in mbar,
Volumenstrom in l/min oder m3/h, Kraefte in N, Masse in kg, Laengen in mm. Wer
das ohne feste Konvention rechnet, produziert Ergebnisse, die um Faktor 60 oder
1000 daneben liegen und trotzdem plausibel aussehen.

Kanonische Einheiten im gesamten Programm (Schicht core bis services):

    Laenge          mm          Feldsuffix _mm
    Flaeche         mm2         Feldsuffix _mm2
    Volumen         mm3 / cm3   Feldsuffix _mm3 / _cm3
    Masse           kg          Feldsuffix _kg
    Kraft           N           Feldsuffix _n
    Druck           Pa          Feldsuffix _pa
    Volumenstrom    m3/s        Feldsuffix _m3s
    Zeit            s           Feldsuffix _s
    Beschleunigung  m/s2        Feldsuffix _ms2
    Anteil          0..1        Feldsuffix _ratio
    Prozent         0..100      Feldsuffix _pct

Der Suffix ist Pflicht. tests/test_architecture.py prueft jedes DTO-Feld gegen
diese Liste - ein Feld namens `pressure` faellt durch, `pressure_pa` nicht.

Unterdruck wird durchgaengig als POSITIVE Druckdifferenz zur Umgebung gefuehrt
(`vacuum_pa`). "-0,6 bar" des Datenblatts sind hier 60000 Pa. Ein negatives
Vorzeichen im Rechenweg waere eine dauerhafte Fehlerquelle; die Umrechnung in
die uebliche Schreibweise passiert erst in der Anzeige.
"""

from __future__ import annotations

#: Normdruck der Umgebung. Einstellbar ueber die Konfiguration, hier nur als
#: Ausgangswert fuer Standorte auf Meereshoehe.
STANDARD_AMBIENT_PA = 101325.0

#: Erdbeschleunigung.
GRAVITY_MS2 = 9.80665

#: Dichte trockener Luft bei 20 C und Normdruck. Bezugsgroesse fuer die
#: Umrechnung von Massen- in Volumenstrom.
AIR_DENSITY_KGM3 = 1.204

#: Spezifische Gaskonstante trockener Luft.
AIR_GAS_CONSTANT = 287.058

#: Isentropenexponent trockener Luft.
AIR_KAPPA = 1.4

#: Bezugstemperatur der Stroemungsrechnung.
STANDARD_TEMPERATURE_K = 293.15

#: Erlaubte Einheitensuffixe fuer DTO-Felder. Wird vom Architekturtest gelesen.
FIELD_SUFFIXES: tuple[str, ...] = (
    "_mm", "_mm2", "_mm3", "_cm3", "_m", "_m2", "_m3",
    "_kg", "_n", "_pa", "_m3s", "_s", "_ms2",
    "_ratio", "_pct", "_deg", "_count", "_factor", "_k",
)


# Druck ------------------------------------------------------------------------

def mbar_to_pa(value_mbar: float) -> float:
    return value_mbar * 100.0


def pa_to_mbar(value_pa: float) -> float:
    return value_pa / 100.0


def bar_to_pa(value_bar: float) -> float:
    return value_bar * 100000.0


def pa_to_bar(value_pa: float) -> float:
    return value_pa / 100000.0


# Volumenstrom -----------------------------------------------------------------

def lpm_to_m3s(value_lpm: float) -> float:
    """Liter pro Minute in Kubikmeter pro Sekunde."""
    return value_lpm / 60000.0


def m3s_to_lpm(value_m3s: float) -> float:
    return value_m3s * 60000.0


def m3h_to_m3s(value_m3h: float) -> float:
    return value_m3h / 3600.0


def m3s_to_m3h(value_m3s: float) -> float:
    return value_m3s * 3600.0


# Laenge und Flaeche -----------------------------------------------------------

def mm_to_m(value_mm: float) -> float:
    return value_mm / 1000.0


def mm2_to_m2(value_mm2: float) -> float:
    return value_mm2 / 1_000_000.0


def m2_to_mm2(value_m2: float) -> float:
    return value_m2 * 1_000_000.0


def mm3_to_cm3(value_mm3: float) -> float:
    return value_mm3 / 1000.0


def cm3_to_m3(value_cm3: float) -> float:
    return value_cm3 / 1_000_000.0


# Kraft und Masse --------------------------------------------------------------

def force_from_pressure(vacuum_pa: float, area_mm2: float) -> float:
    """Haltekraft aus Druckdifferenz und wirksamer Flaeche: F = dp * A."""
    return vacuum_pa * mm2_to_m2(area_mm2)


def mass_from_force(force_n: float, acceleration_ms2: float = GRAVITY_MS2) -> float:
    """Masse, die eine Kraft bei gegebener Beschleunigung traegt."""
    if acceleration_ms2 <= 0.0:
        return 0.0
    return force_n / acceleration_ms2
