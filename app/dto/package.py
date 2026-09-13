"""Das Paket - die Quelle der Wahrheit jeder Berechnung.

Warum max_stack_load_kg hier steht und nicht bei den Palettierbedingungen:
die zulaessige Stapellast ist eine Eigenschaft des Kartons, nicht der Palette.
Derselbe Karton behaelt sie, gleich auf welcher Palette er liegt. Die
Palettierung darf den Wert fuer einen Versuch ueberschreiben, die Herkunft
bleibt aber das Paketformular.

Orientierung: in der Praxis darf ein Karton meist nur in der Ebene gedreht
werden ("oben bleibt oben"). Kippen ist die Ausnahme und muss ausdruecklich
erlaubt werden - deshalb ein Schalter mit dem sicheren Standardwert, statt
einer stillen Annahme im Optimierer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from app.core.result import IssueLevel, ValidationIssue, ValidationReport

#: Plausibilitaetsgrenzen. Bewusst weit gefasst - sie sollen Tippfehler und
#: Einheitenverwechslungen abfangen (Meter statt Millimeter), nicht den
#: Anwendungsbereich beschneiden.
MIN_DIMENSION_MM = 1.0
MAX_DIMENSION_MM = 5000.0
MIN_WEIGHT_KG = 0.001
MAX_WEIGHT_KG = 2000.0
MAX_STACK_LOAD_KG = 20000.0


class Orientation(Enum):
    """Welche Paketachse steht senkrecht."""

    UPRIGHT = "upright"
    TIPPED_LENGTH = "tipped_length"
    TIPPED_WIDTH = "tipped_width"

    @property
    def label(self) -> str:
        return {
            Orientation.UPRIGHT: "Stehend (oben bleibt oben)",
            Orientation.TIPPED_LENGTH: "Auf die Laengsseite gekippt",
            Orientation.TIPPED_WIDTH: "Auf die Schmalseite gekippt",
        }[self]


@dataclass(frozen=True, slots=True)
class PackageSpec:
    """Ein Paket. Alle abhaengigen Berechnungen gehen von diesem Objekt aus."""

    length_mm: float
    width_mm: float
    height_mm: float
    weight_kg: float

    #: Zulaessige Auflast auf einem einzelnen Paket. 0 bedeutet unbegrenzt -
    #: dann entfaellt die Lastpruefung der Palettierung ausdruecklich, statt
    #: sie mit einem erfundenen Wert zu fuehren.
    max_stack_load_kg: float = 0.0

    #: Ob der Optimierer das Paket kippen darf. Aus gutem Grund standardmaessig aus.
    allow_tipping: bool = False

    #: Freitext zur Identifikation, erscheint im Protokoll.
    label: str = ""

    # Abgeleitete Anzeigewerte -------------------------------------------------

    @property
    def volume_mm3(self) -> float:
        return self.length_mm * self.width_mm * self.height_mm

    @property
    def volume_l(self) -> float:
        return self.volume_mm3 / 1_000_000.0

    @property
    def footprint_area_mm2(self) -> float:
        return self.length_mm * self.width_mm

    @property
    def density_kgm3(self) -> float:
        volume_m3 = self.volume_mm3 / 1_000_000_000.0
        return self.weight_kg / volume_m3 if volume_m3 > 0 else 0.0

    @property
    def has_stack_load_limit(self) -> bool:
        return self.max_stack_load_kg > 0.0

    def dimensions_for(self, orientation: Orientation) -> tuple[float, float, float]:
        """Grundflaeche und Hoehe in der gewaehlten Kippstellung."""
        if orientation is Orientation.TIPPED_LENGTH:
            return self.length_mm, self.height_mm, self.width_mm
        if orientation is Orientation.TIPPED_WIDTH:
            return self.height_mm, self.width_mm, self.length_mm
        return self.length_mm, self.width_mm, self.height_mm

    def allowed_orientations(self) -> tuple[Orientation, ...]:
        if self.allow_tipping:
            return (Orientation.UPRIGHT, Orientation.TIPPED_LENGTH, Orientation.TIPPED_WIDTH)
        return (Orientation.UPRIGHT,)


def _check_dimension(name: str, label: str, value: float) -> ValidationIssue | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return ValidationIssue(name, label + ": kein Zahlenwert")
    if math.isnan(value) or math.isinf(value):
        return ValidationIssue(name, label + ": kein endlicher Zahlenwert")
    if value <= 0:
        return ValidationIssue(name, label + " muss groesser als 0 sein")
    if value < MIN_DIMENSION_MM:
        return ValidationIssue(name, label + " ist kleiner als " + format(MIN_DIMENSION_MM, ".0f") + " mm")
    if value > MAX_DIMENSION_MM:
        return ValidationIssue(
            name, label + " ueberschreitet " + format(MAX_DIMENSION_MM, ".0f") + " mm - Eingabe in mm erwartet"
        )
    return None


def validate_package(package: PackageSpec) -> ValidationReport:
    """Prueft ein Paket feldweise. Die Meldungen tragen den Feldnamen, damit
    die Oberflaeche sie am richtigen Eingabefeld anzeigen kann."""
    issues: list[ValidationIssue] = []

    for name, label, value in (
        ("length_mm", "Laenge", package.length_mm),
        ("width_mm", "Breite", package.width_mm),
        ("height_mm", "Hoehe", package.height_mm),
    ):
        issue = _check_dimension(name, label, value)
        if issue is not None:
            issues.append(issue)

    weight = package.weight_kg
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        issues.append(ValidationIssue("weight_kg", "Gewicht: kein Zahlenwert"))
    elif math.isnan(weight) or math.isinf(weight):
        issues.append(ValidationIssue("weight_kg", "Gewicht: kein endlicher Zahlenwert"))
    elif weight <= 0:
        issues.append(ValidationIssue("weight_kg", "Gewicht muss groesser als 0 sein"))
    elif weight < MIN_WEIGHT_KG:
        issues.append(ValidationIssue("weight_kg", "Gewicht ist kleiner als 1 g"))
    elif weight > MAX_WEIGHT_KG:
        issues.append(
            ValidationIssue("weight_kg", "Gewicht ueberschreitet " + format(MAX_WEIGHT_KG, ".0f") + " kg - Eingabe in kg erwartet")
        )

    load = package.max_stack_load_kg
    if not isinstance(load, (int, float)) or isinstance(load, bool) or math.isnan(load) or math.isinf(load):
        issues.append(ValidationIssue("max_stack_load_kg", "Max. Stapellast: kein endlicher Zahlenwert"))
    elif load < 0:
        issues.append(ValidationIssue("max_stack_load_kg", "Max. Stapellast darf nicht negativ sein"))
    elif load > MAX_STACK_LOAD_KG:
        issues.append(
            ValidationIssue("max_stack_load_kg", "Max. Stapellast ueberschreitet " + format(MAX_STACK_LOAD_KG, ".0f") + " kg")
        )
    elif load == 0:
        issues.append(
            ValidationIssue(
                "max_stack_load_kg",
                "Ohne max. Stapellast wird die Belastung der Pakete nicht geprueft",
                IssueLevel.WARNING,
            )
        )
    elif load < package.weight_kg:
        issues.append(
            ValidationIssue(
                "max_stack_load_kg",
                "Max. Stapellast ist kleiner als das Eigengewicht - es passt keine zweite Lage",
                IssueLevel.WARNING,
            )
        )

    return ValidationReport(tuple(issues))
