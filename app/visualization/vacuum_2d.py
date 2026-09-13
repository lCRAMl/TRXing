"""Draufsicht der Vakuumplatte.

Zeichnet Platte, Pakete und Sauger. Die Farbe eines Saugers zeigt seine
Kontaktklasse - und diese Entscheidung trifft ausdruecklich die Engine, nicht
der Renderer (Spezifikation 37). Hier wird nur nachgeschlagen, was im Ergebnis
steht.

Der Unterschied ist nicht theoretisch: die Frage, ob ein Sauger dichtet, haengt
am Dichtlippenring und nicht am Mittelpunkt. Wuerde der Renderer das selbst
entscheiden, muesste er dieselbe Geometrie noch einmal rechnen - und sobald
beide Rechnungen auseinanderlaufen, zeigt die Anzeige etwas anderes an als das
Ergebnis daneben.

Gezeichnet wird der Dichtlippenring, nicht die Nenngroesse: er ist der Kreis,
ueber den die Engine entscheidet, und damit der, den man sehen will.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.dto.suction import ContactClass
from app.dto.vacuum import VacuumResult
from app.visualization.colors import toned
from app.visualization.theme import MONO_FAMILY, PALETTE

#: Rand um die Plattenzeichnung. Oben steht statt dessen die Legende.
MARGIN_PX = 52

#: Streifen, den die Legende ueber der Zeichnung belegt.
LEGEND_HEIGHT_PX = 98

#: Aussenradius des Beispielsaugers in der Legende. Die beiden inneren Kreise
#: leiten sich daraus im Verhaeltnis der echten Durchmesser ab - das
#: Verhaeltnis ist die Aussage der Legende.
LEGEND_SAMPLE_RADIUS_PX = 21.0

#: Zeilenabstand der drei Beschriftungen neben dem Beispielsauger.
LEGEND_LINE_PX = 14.0

#: Abstand vom Beispielsauger zur Beschriftung und Breite der Wertespalte.
LEGEND_TEXT_GAP_PX = 34.0
LEGEND_VALUE_COLUMN_PX = 230.0

_CONTACT_COLORS = {
    ContactClass.SEALED: PALETTE.cup_sealed,
    ContactClass.PARTIAL: PALETTE.cup_partial,
    ContactClass.OPEN: PALETTE.cup_open,
}

#: Strich der Aussenkontur - hier stossen zwei Sauger aneinander.
#:
#: Die Kontur ist der Ring, an dem die Verteilung ihre Grenze findet: naeher als
#: Aussenmass plus Mindestabstand koennen zwei Sauger nicht stehen. Wer die
#: Platte auslegt, will genau das sehen, deshalb ist der Strich kraeftig genug,
#: um auf der Plattenflaeche zu bestehen. Gestrichelt statt durchgezogen, damit
#: er nicht mit dem Dichtlippenring verwechselt wird, der ueber dicht oder offen
#: entscheidet.
#:
#: Zeichnung und Legende holen ihn von hier - sonst laufen beide auseinander,
#: und die Legende erklaert einen Strich, den es nicht gibt.
OUTLINE_PEN_WIDTH = 1.2
OUTLINE_PEN_STYLE = Qt.PenStyle.DashLine

#: Ab welchem Unterschied zwischen Aussenmass und Dichtlippe die Kontur
#: gezeichnet wird. Darunter faellt sie mit dem Dichtlippenring zusammen und
#: macht ihn nur unscharf.
MIN_OUTLINE_GAP_PX = 1.0


class Vacuum2DView(QWidget):
    """Draufsicht der Saugerplatte mit den Paketen darunter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: VacuumResult | None = None
        self._stale = False
        self.setMinimumSize(380, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoFillBackground(True)

    def set_result(self, result: VacuumResult | None) -> None:
        self._result = result
        self._stale = False
        self.update()

    def set_stale(self, stale: bool) -> None:
        self._stale = stale
        self.update()

    # Zeichnen -----------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt-Namensschema
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PALETTE.canvas))

        result = self._result
        if result is None:
            painter.setPen(QColor(PALETTE.text_muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Noch kein Ergebnis - Werte eingeben oder auf 'Berechnen' klicken.")
            painter.end()
            return

        plate_l = result.plate.length_mm
        plate_w = result.plate.width_mm
        # Oben der Legendenstreifen, sonst rundum der Rand. Die Legende in die
        # Zeichnung zu legen waere platzsparender, deckte aber genau die Sauger
        # zu, die sie erklaert.
        area = self.rect().adjusted(MARGIN_PX, LEGEND_HEIGHT_PX, -MARGIN_PX, -MARGIN_PX)
        scale = min(area.width() / plate_l, area.height() / plate_w) if plate_l > 0 and plate_w > 0 else 0.0
        if scale <= 0:
            painter.end()
            return

        width_px = plate_l * scale
        height_px = plate_w * scale
        origin_x = area.x() + (area.width() - width_px) / 2.0
        origin_y = area.y() + (area.height() - height_px) / 2.0

        if self._stale:
            painter.setOpacity(0.45)

        plate_rect = QRectF(origin_x, origin_y, width_px, height_px)
        painter.setBrush(QBrush(QColor(PALETTE.plate_fill)))
        painter.setPen(QPen(QColor(PALETTE.plate_edge), 2))
        painter.drawRect(plate_rect)

        self._draw_packages(painter, result, origin_x, origin_y, height_px, scale)

        # Die Plattenkontur noch einmal darueber. Die Platte darf kleiner sein
        # als das, was sie hebt - dann liegen die Pakete ueber ihr und verdecken
        # ihren Rand vollstaendig. Gerade dann muss aber erkennbar bleiben, wo
        # die Platte aufhoert: nur darunter koennen Sauger sitzen.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(PALETTE.plate_edge), 2))
        painter.drawRect(plate_rect)

        self._draw_cups(painter, result, origin_x, origin_y, height_px, scale)
        painter.setOpacity(1.0)
        self._draw_dimensions(painter, result, origin_x, origin_y, width_px, height_px)
        self._draw_legend(painter, result)
        painter.end()

    def _draw_packages(
        self, painter: QPainter, result: VacuumResult, origin_x: float,
        origin_y: float, height_px: float, scale: float,
    ) -> None:
        painter.setBrush(QBrush(QColor(PALETTE.package_fill)))
        painter.setPen(QPen(QColor(PALETTE.package_edge), 1.4))
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)

        for index, (x_mm, y_mm, length_mm, width_mm) in enumerate(result.package_rects):
            rect = QRectF(
                origin_x + x_mm * scale,
                origin_y + height_px - (y_mm + width_mm) * scale,
                length_mm * scale,
                width_mm * scale,
            )
            painter.drawRect(rect)
            if rect.width() > 40 and rect.height() > 20:
                painter.setPen(QColor(PALETTE.text))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Paket " + str(index + 1))
                painter.setPen(QPen(QColor(PALETTE.package_edge), 1.4))

    def _draw_cups(
        self, painter: QPainter, result: VacuumResult, origin_x: float,
        origin_y: float, height_px: float, scale: float,
    ) -> None:
        """Zeichnet je Sauger drei Kreise mit verschiedener Bedeutung.

        Das ist keine Verzierung - die drei Durchmesser sind der Kern des
        Missverstaendnisses, das bei Saugerplatten zu knapp ausgelegten Anlagen
        fuehrt. Bei einem SPB2 30 sind sie:

            Aussenmass unter Vakuum   Dmax(S)  34,0 mm   Platzbedarf im Raster
            Auflagebereich            Ds       31,4 mm   Dichtlippe, entscheidet
                                                         ueber dicht oder offen
            Wirkungsbereich           d2       16,9 mm   traegt die Kraft

        Der Wirkungsbereich hat nur ein Viertel der Flaeche des sichtbaren
        Saugers. Wer die Haltekraft aus dem Aussenmass schaetzt, rechnet sich
        um den Faktor vier reich.

        Entschieden wird auch hier nichts: welche Klasse ein Sauger hat, steht
        im Ergebnis (Spezifikation 37).
        """
        cup = result.cup
        by_index = {c.placement_index: c for c in result.contacts}

        outer_px = cup.outer_diameter_mm / 2.0 * scale
        seal_px = cup.sealing_lip_diameter_mm / 2.0 * scale
        effective_px = cup.effective_force_diameter_mm / 2.0 * scale

        # Unterhalb weniger Bildpunkte sind drei Kreise nicht mehr zu
        # unterscheiden - dann bleibt der Wirkungsbereich weg, sonst wird die
        # Darstellung zu einem Farbklecks.
        detailed = seal_px >= 5.0

        # Die Aussenkontur bleibt auch dann stehen: sie ist der aeusserste der
        # drei Kreise und damit der einzige, an dem sich ablesen laesst, wo zwei
        # Sauger aneinanderstossen. Sie faellt nur weg, wenn sie ohnehin auf dem
        # Dichtlippenring laege.
        show_outline = outer_px - seal_px >= MIN_OUTLINE_GAP_PX

        for placement in result.placements:
            entry = by_index.get(placement.index)
            contact = entry.contact if entry else ContactClass.OPEN
            color = QColor(_CONTACT_COLORS.get(contact, PALETTE.cup_open))

            center = QPointF(
                origin_x + placement.center_x_mm * scale,
                origin_y + height_px - placement.center_y_mm * scale,
            )

            if show_outline:
                # Aussenmass unter Vakuum: der Platz, den der Sauger braucht.
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(PALETTE.cup_outline), OUTLINE_PEN_WIDTH,
                                    OUTLINE_PEN_STYLE))
                painter.drawEllipse(center, outer_px, outer_px)

            # Auflagebereich: der Dichtlippenring. Gefuellt nur, was traegt -
            # damit ist der Unterschied auch im Ausdruck ohne Farbe erkennbar.
            if contact is ContactClass.SEALED:
                painter.setBrush(QBrush(toned(color, 178)))
            elif contact is ContactClass.PARTIAL:
                painter.setBrush(QBrush(toned(color, 186)))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, 1.4))
            painter.drawEllipse(center, seal_px, seal_px)

            if detailed and effective_px > 1.0:
                # Wirkungsbereich: nur wo er auch wirkt, also bei dichtenden
                # Saugern. Bei einem offenen waere eine gefuellte Wirkflaeche
                # eine Falschaussage.
                if contact is ContactClass.SEALED:
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(color.darker(130), 0.8))
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(color, 0.8, Qt.PenStyle.DashLine))
                painter.drawEllipse(center, effective_px, effective_px)

    def _draw_dimensions(
        self, painter: QPainter, result: VacuumResult, x: float, y: float, w: float, h: float
    ) -> None:
        painter.setPen(QPen(QColor(PALETTE.text_muted), 1))
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)

        painter.drawText(
            QRectF(x, y + h + 6, w, 16), Qt.AlignmentFlag.AlignCenter,
            format(result.plate.length_mm, ".0f") + " mm",
        )
        painter.save()
        painter.translate(x - 10, y + h / 2.0)
        painter.rotate(-90)
        painter.drawText(
            QRectF(-h / 2.0, -16, h, 16), Qt.AlignmentFlag.AlignCenter,
            format(result.plate.width_mm, ".0f") + " mm",
        )
        painter.restore()

    def _draw_legend(self, painter: QPainter, result: VacuumResult) -> None:
        """Drei Zeilen: Kontaktklassen, die drei Durchmesser, das Rastermass."""
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)

        self._draw_contact_legend(painter, result, y=12.0)
        self._draw_diameter_legend(painter, result, y=30.0)
        self._draw_pitch_legend(painter, result, y=86.0)

    def _draw_contact_legend(self, painter: QPainter, result: VacuumResult, y: float) -> None:
        """Was die Farbe eines Saugers bedeutet, und wie viele es davon gibt."""
        metrics = painter.fontMetrics()
        x = 8.0
        for color, label, filled in (
            (PALETTE.cup_sealed, "wirksam " + str(result.sealed_count), True),
            (PALETTE.cup_partial, "teilweise " + str(result.partial_count), True),
            (PALETTE.cup_open, "offen " + str(result.open_count), False),
        ):
            painter.setPen(QPen(QColor(color), 1.4))
            painter.setBrush(QBrush(QColor(color)) if filled else Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(x + 5, y), 5, 5)
            painter.setPen(QColor(PALETTE.text_muted))
            width = metrics.horizontalAdvance(label) + 8
            painter.drawText(QRectF(x + 14, y - 8, width, 16), Qt.AlignmentFlag.AlignLeft, label)
            x += 22 + width

        if self._stale:
            painter.setPen(QColor(PALETTE.stale))
            painter.drawText(QRectF(x + 10, y - 8, 120, 16), Qt.AlignmentFlag.AlignLeft, "VERALTET")

    def _draw_diameter_legend(self, painter: QPainter, result: VacuumResult, y: float) -> None:
        """Die drei Durchmesser an EINEM Sauger im richtigen Verhaeltnis.

        Drei gleich grosse Kreise nebeneinander waeren einfacher zu zeichnen
        und sagten das Gegenteil: das Verhaeltnis IST die Aussage. Der
        Wirkungsbereich misst gut die Haelfte des Aussenmasses und traegt damit
        nur ein Viertel der Flaeche - wer die Haltekraft aus dem sichtbaren
        Sauger schaetzt, rechnet sich um den Faktor vier reich.

        Die Beschriftungen haengen an Hinweislinien, die den zugehoerigen Kreis
        beruehren. Eine Legende, die nur drei Zeilen untereinander auffuehrt,
        laesst offen, welcher Kreis welcher ist.
        """
        cup = result.cup
        outer_r = LEGEND_SAMPLE_RADIUS_PX
        seal_r = outer_r * cup.sealing_lip_diameter_mm / max(cup.outer_diameter_mm, 1e-9)
        effective_r = outer_r * cup.effective_force_diameter_mm / max(cup.outer_diameter_mm, 1e-9)

        center = QPointF(8.0 + outer_r, y + outer_r)
        muted = QColor(PALETTE.text_muted)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(PALETTE.cup_outline), OUTLINE_PEN_WIDTH, OUTLINE_PEN_STYLE))
        painter.drawEllipse(center, outer_r, outer_r)

        painter.setPen(QPen(muted, 1.4))
        painter.drawEllipse(center, seal_r, seal_r)

        painter.setBrush(QBrush(muted))
        painter.setPen(QPen(muted, 1.0))
        painter.drawEllipse(center, effective_r, effective_r)

        text_x = center.x() + outer_r + LEGEND_TEXT_GAP_PX

        # Zahlen in fester Laufweite, wie ueberall in der Anwendung: die
        # Stellen stehen dann untereinander und lassen sich vergleichen.
        label_font = QFont(painter.font())
        value_font = QFont(MONO_FAMILY.split(",")[0].strip())
        value_font.setPointSize(label_font.pointSize())

        rows = (
            (outer_r, -LEGEND_LINE_PX, "Aussenmass unter Vakuum", cup.outer_diameter_mm),
            (seal_r, 0.0, "Auflagebereich (Dichtlippe)", cup.sealing_lip_diameter_mm),
            (effective_r, LEGEND_LINE_PX, "Wirkungsbereich (Kraft)", cup.effective_force_diameter_mm),
        )
        for radius, offset_y, label, value_mm in rows:
            line_y = center.y() + offset_y
            # Ansatzpunkt auf dem Kreis in der Hoehe der Zeile. Liegt die Zeile
            # ueber dem Kreis, beginnt die Linie an seinem Scheitel.
            reach = math.sqrt(max(0.0, radius * radius - offset_y * offset_y))
            painter.setPen(QPen(muted, 1.0))
            painter.drawLine(
                QPointF(center.x() + reach, line_y), QPointF(text_x - 6.0, line_y)
            )

            painter.setFont(label_font)
            painter.setPen(QColor(PALETTE.text_muted))
            painter.drawText(
                QRectF(text_x, line_y - 8, LEGEND_VALUE_COLUMN_PX - 60, 16),
                Qt.AlignmentFlag.AlignLeft, label,
            )
            painter.setFont(value_font)
            painter.setPen(QColor(PALETTE.text))
            painter.drawText(
                QRectF(text_x, line_y - 8, LEGEND_VALUE_COLUMN_PX, 16),
                Qt.AlignmentFlag.AlignRight, format(value_mm, ".1f") + " mm",
            )

        painter.setFont(label_font)

    def _draw_pitch_legend(self, painter: QPainter, result: VacuumResult, y: float) -> None:
        """Rastermass, Aussenmass und Mindestabstand nebeneinander.

        Die haeufigste Frage an dieser Zeichnung ist, warum die Sauger nicht
        aneinanderstossen. Die Antwort ist der lichte Mindestabstand, und sie
        gehoert dorthin, wo die Frage entsteht.

        Vier Zahlen nebeneinander und keine Rechnung: nur beim dichten Raster
        ist der Spaltenabstand die Summe aus Aussenmass und Mindestabstand. Ein
        gespreiztes Raster verteilt den Rest der Platte zusaetzlich darauf.

        Spalten- und Reihenabstand stehen getrennt da, weil sie in der
        dichtesten Packung verschieden sind: dort ist der Reihenabstand das
        0,866-fache des Spaltenabstands und damit kleiner als das Aussenmass -
        die versetzten Reihen greifen ineinander, der Mittenabstand zu JEDEM
        Nachbarn bleibt trotzdem der volle Spaltenabstand. Eine einzige Zahl
        "Rastermass" koennte das nicht sagen.
        """
        if max(result.pitch_x_mm, result.pitch_y_mm) <= 0.0:
            return

        spacing = result.plate.min_spacing_mm
        text = (
            "Spaltenabstand " + format(result.pitch_x_mm, ".1f")
            + " mm     Reihenabstand " + format(result.pitch_y_mm, ".1f")
            + " mm     Aussenmass " + format(result.cup.outer_diameter_mm, ".1f")
            + " mm     Saugerabstand " + format(spacing, ".1f") + " mm"
        )
        if spacing <= 0.05:
            text += "   (die Sauger stossen aneinander)"

        painter.setPen(QColor(PALETTE.text_muted))
        painter.drawText(QRectF(8.0, y - 8, 760.0, 16), Qt.AlignmentFlag.AlignLeft, text)
