"""Gemeinsame Datenobjekte an der Schichtgrenze.

Alle DTOs sind eingefroren und tragen Daten, kein Verhalten. Die wenigen
Eigenschaften hier sind reine Ableitungen aus den eigenen Feldern (Flaeche aus
Kantenlaengen) - sie holen keine Daten, rufen keine Engine und treffen keine
fachliche Entscheidung.

Numerische Felder tragen ohne Ausnahme das Einheitensuffix aus
app/core/units.py. tests/test_architecture.py erzwingt das.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Rect2D:
    """Achsparalleles Rechteck. Ursprung links unten."""

    x_mm: float
    y_mm: float
    length_mm: float
    width_mm: float

    @property
    def area_mm2(self) -> float:
        return self.length_mm * self.width_mm

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.length_mm

    @property
    def top_mm(self) -> float:
        return self.y_mm + self.width_mm

    @property
    def center_x_mm(self) -> float:
        return self.x_mm + self.length_mm / 2.0

    @property
    def center_y_mm(self) -> float:
        return self.y_mm + self.width_mm / 2.0

    def contains_point(self, x_mm: float, y_mm: float) -> bool:
        return self.x_mm <= x_mm <= self.right_mm and self.y_mm <= y_mm <= self.top_mm


@dataclass(frozen=True, slots=True)
class Circle2D:
    """Kreis in der Draufsicht. Beschreibt Saugerflaechen und Dichtlippenringe."""

    center_x_mm: float
    center_y_mm: float
    diameter_mm: float

    @property
    def radius_mm(self) -> float:
        return self.diameter_mm / 2.0

    @property
    def area_mm2(self) -> float:
        return math.pi * self.radius_mm * self.radius_mm


@dataclass(frozen=True, slots=True)
class Footprint:
    """Standflaeche einer Platzierung in der Ebene.

    rotated meint die Drehung um 90 Grad in der Ebene - nicht das Kippen. Ob
    eine Kante hochkant stehen darf, entscheidet die Orientierung des Pakets.
    """

    x_mm: float
    y_mm: float
    length_mm: float
    width_mm: float
    rotated: bool = False

    def as_rect(self) -> Rect2D:
        return Rect2D(self.x_mm, self.y_mm, self.length_mm, self.width_mm)


class ViewMode(Enum):
    """Ansichtsumschaltung des Palettentabs."""

    TOP_2D = "2d"
    SCENE_3D = "3d"

    @property
    def label(self) -> str:
        return {ViewMode.TOP_2D: "2D Draufsicht", ViewMode.SCENE_3D: "3D Ansicht"}[self]


@dataclass(frozen=True, slots=True)
class CalculationMeta:
    """Herkunftsangaben, die jedes Ergebnis mitfuehrt (Spezifikation 40).

    state_revision ist der Zaehler des Anwendungszustands zum Zeitpunkt der
    Anfrage. Steigt er danach, ist das Ergebnis veraltet - genau daran erkennen
    die Tabs, dass eine Aenderung an den Paketdaten ihre Anzeige
    entwertet hat, ohne dass Signale von Tab zu Tab gereicht werden muessen.
    """

    module_id: str
    algorithm_version: str
    request_id: int = 0
    state_revision: int = 0
    calculation_id: str = ""
    duration_s: float = 0.0
