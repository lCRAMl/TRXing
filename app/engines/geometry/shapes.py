"""Geometrische Grundoperationen.

Qt-frei und ohne Fremdbibliothek: diese Funktionen sind der Kern beider
Rechenmodule und muessen ohne Oberflaeche pruefbar bleiben.

Der wichtigste Teil ist die exakte Kreis-Rechteck-Ueberdeckung. Spezifikation 19
verbietet ausdruecklich, einen Sauger nur nach seinem Mittelpunkt zu zaehlen.
Statt einer Naeherung per Zufallsstichprobe steht hier die geschlossene Loesung:
das Integral ueber die Kreisflaeche innerhalb eines achsparallelen Rechtecks
laesst sich aus vier Eckbeitraegen zusammensetzen. Das Ergebnis ist exakt und
reproduzierbar - beides fordert Spezifikation 39.
"""

from __future__ import annotations

import math

#: Toleranz fuer Vergleiche in Millimeter. Gross genug gegen Rundungsfehler aus
#: Gleitkommaarithmetik, klein genug, um keine echte Ueberlappung zu verdecken.
EPSILON_MM = 1e-9


def rect_overlap_area_mm2(
    ax_mm: float, ay_mm: float, al_mm: float, aw_mm: float,
    bx_mm: float, by_mm: float, bl_mm: float, bw_mm: float,
) -> float:
    """Ueberdeckung zweier achsparalleler Rechtecke."""
    dx = min(ax_mm + al_mm, bx_mm + bl_mm) - max(ax_mm, bx_mm)
    dy = min(ay_mm + aw_mm, by_mm + bw_mm) - max(ay_mm, by_mm)
    return dx * dy if dx > 0.0 and dy > 0.0 else 0.0


def rect_contains_rect(
    outer_x_mm: float, outer_y_mm: float, outer_l_mm: float, outer_w_mm: float,
    inner_x_mm: float, inner_y_mm: float, inner_l_mm: float, inner_w_mm: float,
    tolerance_mm: float = EPSILON_MM,
) -> bool:
    return (
        inner_x_mm >= outer_x_mm - tolerance_mm
        and inner_y_mm >= outer_y_mm - tolerance_mm
        and inner_x_mm + inner_l_mm <= outer_x_mm + outer_l_mm + tolerance_mm
        and inner_y_mm + inner_w_mm <= outer_y_mm + outer_w_mm + tolerance_mm
    )


def circle_fits_in_rect(
    center_x_mm: float, center_y_mm: float, radius_mm: float,
    rect_x_mm: float, rect_y_mm: float, rect_l_mm: float, rect_w_mm: float,
    tolerance_mm: float = EPSILON_MM,
) -> bool:
    """Ob ein Kreis vollstaendig im Rechteck liegt.

    Das ist das Dichtheitskriterium eines Saugers: der Dichtlippenring muss
    ganz auf der Kartonflaeche aufliegen. Beruehrt er die Kante, ist die
    Dichtung unterbrochen.
    """
    return (
        center_x_mm - radius_mm >= rect_x_mm - tolerance_mm
        and center_y_mm - radius_mm >= rect_y_mm - tolerance_mm
        and center_x_mm + radius_mm <= rect_x_mm + rect_l_mm + tolerance_mm
        and center_y_mm + radius_mm <= rect_y_mm + rect_w_mm + tolerance_mm
    )


def _circle_segment_area(radius_mm: float, x_mm: float) -> float:
    """Flaeche zwischen Kreisrand und Sehne im Abstand x vom Mittelpunkt.

    Stammfunktion von sqrt(r^2 - t^2), ausgewertet an der Stelle x. Aus dieser
    einen Funktion setzt sich die gesamte Kreis-Rechteck-Ueberdeckung zusammen.
    """
    x = max(-radius_mm, min(radius_mm, x_mm))
    return 0.5 * (x * math.sqrt(max(0.0, radius_mm * radius_mm - x * x))
                  + radius_mm * radius_mm * math.asin(x / radius_mm if radius_mm > 0 else 0.0))


def _quarter_area(radius_mm: float, x_mm: float, y_mm: float) -> float:
    """Flaeche des Kreises (Mittelpunkt im Ursprung) im Bereich t <= x, u <= y,
    beschraenkt auf den Viertelbereich mit positiven Koordinaten.

    Zusammen mit der Inklusions-Exklusions-Formel unten ergibt sich daraus die
    Ueberdeckung eines beliebigen achsparallelen Rechtecks.
    """
    if x_mm <= 0.0 or y_mm <= 0.0:
        return 0.0
    x = min(x_mm, radius_mm)
    y = min(y_mm, radius_mm)
    if x * x + y * y >= radius_mm * radius_mm:
        # Die Ecke liegt ausserhalb des Kreises: der Bereich besteht aus einem
        # Rechteckteil und zwei Kreisabschnitten.
        x_at_y = math.sqrt(max(0.0, radius_mm * radius_mm - y * y))
        return (
            x_at_y * y
            + (_circle_segment_area(radius_mm, x) - _circle_segment_area(radius_mm, x_at_y))
        )
    # Die Ecke liegt innerhalb des Kreises: der Bereich ist das volle Rechteck.
    return x * y


def circle_rect_overlap_area_mm2(
    center_x_mm: float, center_y_mm: float, radius_mm: float,
    rect_x_mm: float, rect_y_mm: float, rect_l_mm: float, rect_w_mm: float,
) -> float:
    """Exakte Ueberdeckung eines Kreises mit einem achsparallelen Rechteck.

    Das Rechteck wird relativ zum Kreismittelpunkt betrachtet; die Flaeche ergibt
    sich aus vier Eckbeitraegen nach Inklusion und Exklusion:

        A = Q(x2,y2) - Q(x1,y2) - Q(x2,y1) + Q(x1,y1)

    wobei Q die Flaeche des Kreises links unterhalb des Punktes ist. Jeder
    Quadrant wird getrennt behandelt, damit die Vorzeichen stimmen.
    """
    if radius_mm <= 0.0 or rect_l_mm <= 0.0 or rect_w_mm <= 0.0:
        return 0.0

    x1 = rect_x_mm - center_x_mm
    x2 = rect_x_mm + rect_l_mm - center_x_mm
    y1 = rect_y_mm - center_y_mm
    y2 = rect_y_mm + rect_w_mm - center_y_mm

    def _signed(x: float, y: float) -> float:
        """Flaeche des Kreises im Rechteck [0..x] x [0..y], mit Vorzeichen fuer
        negative Koordinaten - dadurch gilt die Formel in allen Quadranten."""
        sign = (1.0 if x >= 0 else -1.0) * (1.0 if y >= 0 else -1.0)
        return sign * _quarter_area(radius_mm, abs(x), abs(y))

    area = _signed(x2, y2) - _signed(x1, y2) - _signed(x2, y1) + _signed(x1, y1)
    return max(0.0, min(area, math.pi * radius_mm * radius_mm))


def bounding_box(
    rects: list[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    """Umschliessendes Rechteck als (x, y, laenge, breite)."""
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


def any_overlap(rects: list[tuple[float, float, float, float]], tolerance_mm: float = 1e-6) -> bool:
    """Ob sich zwei Rechtecke der Liste ueberschneiden.

    Fuer die Pruefung in den Tests gedacht: ein Muster, das Pakete uebereinander
    legt, ist ein Fehler und kein Ergebnis. Quadratisch in der Anzahl - bei den
    hier auftretenden Lagengroessen unkritisch.
    """
    for i in range(len(rects)):
        ax, ay, al, aw = rects[i]
        for j in range(i + 1, len(rects)):
            bx, by, bl, bw = rects[j]
            if rect_overlap_area_mm2(ax, ay, al, aw, bx, by, bl, bw) > tolerance_mm:
                return True
    return False
