"""2D-Draufsicht der Palette.

Der Renderer zeichnet, was im PalletResult steht - mehr nicht. Er entscheidet
nicht, ob ein Paket passt, wie es gedreht ist oder ob es ueberlastet ist; das
steht alles schon im Ergebnis (Spezifikation 37).

Wer das aufweicht, bekommt zwei Wahrheiten: die der Engine und die der Anzeige.
Sobald sie auseinanderlaufen, glaubt der Benutzer der Anzeige.

Dargestellt werden Palette, Pakete der gewaehlten Ebene, Drehung, Bemassung und
die freie Flaeche. Die Farbe eines Pakets kommt aus seiner Lastbewertung, die
ebenfalls im Ergebnis steht.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.dto.pallet import Layer, LoadStatus, PalletResult
from app.visualization.colors import toned
from app.visualization.theme import PALETTE

#: Rand um die Zeichnung in Bildpunkten - Platz fuer die Bemassung.
MARGIN_PX = 46


class Pallet2DView(QWidget):
    """Draufsicht einer Ebene."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: PalletResult | None = None
        self._layer_index = 0
        self._stale = False
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoFillBackground(True)

    # Daten --------------------------------------------------------------------

    def set_result(self, result: PalletResult | None) -> None:
        self._result = result
        self._layer_index = 0
        self._stale = False
        self.update()

    def set_layer(self, index: int) -> None:
        self._layer_index = index
        self.update()

    def set_stale(self, stale: bool) -> None:
        """Veraltete Ergebnisse werden blass gezeichnet - sie stimmen nicht
        mehr zu den Eingaben, sind aber besser als ein leeres Feld."""
        self._stale = stale
        self.update()

    def layer_count(self) -> int:
        return self._result.layer_count if self._result else 0

    # Zeichnen -----------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt-Namensschema
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PALETTE.canvas))

        result = self._result
        if result is None or not result.layers:
            self._draw_placeholder(painter, "Noch kein Ergebnis - auf 'Berechnen' klicken.")
            painter.end()
            return

        layer = result.layer(self._layer_index) or result.layers[0]
        pallet_l = result.pallet.usable_length_mm
        pallet_w = result.pallet.usable_width_mm
        if pallet_l <= 0 or pallet_w <= 0:
            self._draw_placeholder(painter, "Palettenmasse unbrauchbar.")
            painter.end()
            return

        area = self.rect().adjusted(MARGIN_PX, MARGIN_PX, -MARGIN_PX, -MARGIN_PX)
        scale = min(area.width() / pallet_l, area.height() / pallet_w)
        if scale <= 0:
            painter.end()
            return

        width_px = pallet_l * scale
        height_px = pallet_w * scale
        origin_x = area.x() + (area.width() - width_px) / 2.0
        origin_y = area.y() + (area.height() - height_px) / 2.0

        if self._stale:
            painter.setOpacity(0.45)

        self._draw_pallet(painter, origin_x, origin_y, width_px, height_px)
        self._draw_placements(painter, result, layer, origin_x, origin_y, height_px, scale)
        painter.setOpacity(1.0)
        self._draw_dimensions(painter, result, origin_x, origin_y, width_px, height_px)
        self._draw_legend(painter, result, layer)
        painter.end()

    def _draw_placeholder(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor(PALETTE.text_muted))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_pallet(self, painter: QPainter, x: float, y: float, w: float, h: float) -> None:
        painter.setBrush(QBrush(QColor(PALETTE.pallet_fill)))
        painter.setPen(QPen(QColor(PALETTE.pallet_edge), 2))
        painter.drawRect(QRectF(x, y, w, h))

    def _draw_placements(
        self, painter: QPainter, result: PalletResult, layer: Layer, origin_x: float,
        origin_y: float, height_px: float, scale: float,
    ) -> None:
        status_by_index = {
            entry.package_index: entry.status for entry in result.load.per_package
        } if result.load.checked else {}

        font = QFont(painter.font())
        font.setPointSize(max(6, int(7 * min(2.0, scale * 40))))
        painter.setFont(font)

        for placement in layer.placements:
            # Die Y-Achse der Zeichnung zeigt nach unten, die der Geometrie nach
            # oben. Ohne die Spiegelung laege die Lage auf dem Kopf.
            left = origin_x + placement.x_mm * scale
            top = origin_y + height_px - (placement.y_mm + placement.width_mm) * scale
            rect = QRectF(left, top, placement.length_mm * scale, placement.width_mm * scale)

            status = status_by_index.get(placement.package_index, LoadStatus.OK)
            if status is LoadStatus.CRITICAL:
                fill, edge = toned(PALETTE.error, 160), QColor(PALETTE.error)
            elif status is LoadStatus.WARNING:
                fill, edge = toned(PALETTE.warning, 170), QColor(PALETTE.warning)
            elif placement.rotated:
                fill, edge = QColor(PALETTE.package_rotated_fill), QColor(PALETTE.package_rotated_edge)
            else:
                fill, edge = QColor(PALETTE.package_fill), QColor(PALETTE.package_edge)

            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(edge, 1.2))
            painter.drawRect(rect)

            if rect.width() > 26 and rect.height() > 16:
                painter.setPen(QColor(PALETTE.text))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(placement.package_index + 1))
            if placement.rotated and rect.width() > 34 and rect.height() > 24:
                self._draw_rotation_marker(painter, rect, edge)

    @staticmethod
    def _draw_rotation_marker(painter: QPainter, rect: QRectF, color: QColor) -> None:
        """Kleiner Winkel in der Ecke: dieses Paket liegt quer.

        Die Farbe allein reicht nicht - wer die Ansicht ausdruckt oder eine
        Rotschwaeche hat, sieht den Unterschied sonst nicht.
        """
        size = min(9.0, rect.width() / 4.0, rect.height() / 4.0)
        corner = QPointF(rect.right() - 3, rect.top() + 3)
        marker = QPolygonF([
            corner,
            QPointF(corner.x() - size, corner.y()),
            QPointF(corner.x(), corner.y() + size),
        ])
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(marker)

    def _draw_dimensions(
        self, painter: QPainter, result: PalletResult, x: float, y: float, w: float, h: float
    ) -> None:
        painter.setPen(QPen(QColor(PALETTE.text_muted), 1))
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)

        length_text = format(result.pallet.usable_length_mm, ".0f") + " mm"
        width_text = format(result.pallet.usable_width_mm, ".0f") + " mm"

        painter.drawLine(QPointF(x, y + h + 16), QPointF(x + w, y + h + 16))
        painter.drawLine(QPointF(x, y + h + 12), QPointF(x, y + h + 20))
        painter.drawLine(QPointF(x + w, y + h + 12), QPointF(x + w, y + h + 20))
        painter.drawText(
            QRectF(x, y + h + 18, w, 16), Qt.AlignmentFlag.AlignCenter, length_text
        )

        painter.drawLine(QPointF(x - 16, y), QPointF(x - 16, y + h))
        painter.drawLine(QPointF(x - 20, y), QPointF(x - 12, y))
        painter.drawLine(QPointF(x - 20, y + h), QPointF(x - 12, y + h))
        painter.save()
        painter.translate(x - 22, y + h / 2.0)
        painter.rotate(-90)
        painter.drawText(QRectF(-h / 2.0, -16, h, 16), Qt.AlignmentFlag.AlignCenter, width_text)
        painter.restore()

    def _draw_legend(self, painter: QPainter, result: PalletResult, layer: Layer) -> None:
        free_ratio = max(0.0, 1.0 - layer.footprint_utilization_ratio)
        text = (
            "Ebene " + str(layer.index + 1) + " von " + str(result.layer_count)
            + "   |   " + str(layer.count) + " Pakete"
            + "   |   Belegt " + format(layer.footprint_utilization_ratio * 100.0, ".1f") + " %"
            + "   |   Frei " + format(free_ratio * 100.0, ".1f") + " %"
        )
        if self._stale:
            text += "   |   VERALTET"
        painter.setPen(QColor(PALETTE.stale if self._stale else PALETTE.text_muted))
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(QRectF(4, 4, self.width() - 8, 18), Qt.AlignmentFlag.AlignLeft, text)
