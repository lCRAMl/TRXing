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
app/engines/geometry/shapes.py) und ausgegeben - sie ist die Kennzahl, an der
man sieht, wie knapp ein Sauger daneben liegt.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dto.common import Footprint
from app.dto.suction import ContactClass, CupContact, SuctionCupSpec, SuctionPlacement
from app.engines.geometry.shapes import circle_fits_in_rect, circle_rect_overlap_area_mm2
from app.engines.vacuum.force import datasheet_effective_area_mm2


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
