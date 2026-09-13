"""3D-Ansicht der Palette mit PyVista.

Diese Datei ist die einzige Stelle im Programm, die PyVista oder VTK kennt.
Alles andere spricht ueber den Vertrag Scene3D in adapters.py mit ihr. Ein
Wechsel auf eine andere Bibliothek betrifft damit genau diese Datei.

Gezeichnet werden die Quader aus dem PalletResult - nichts wird hier berechnet.
Die Farbe eines Pakets kommt aus seiner Lastbewertung, die Drehung aus dem
Platzierungs-DTO.

Die Kamerabedienung (Drehen, Zoom, Verschieben) bringt PyVista mit; sie wird
hier nur eingestellt, nicht nachgebaut.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtWidgets import QWidget

from app.dto.pallet import Layer, LoadStatus, PalletResult
from app.visualization.theme import PALETTE

_STATUS_COLORS = {
    LoadStatus.OK: PALETTE.package_fill,
    LoadStatus.WARNING: PALETTE.warning,
    LoadStatus.CRITICAL: PALETTE.error,
}

#: Ab dieser Anzahl werden nur noch die von aussen sichtbaren Pakete gezeichnet.
#:
#: Nicht wegen der Aufbauzeit - die ist seit _boxes_to_mesh unabhaengig von der
#: Stueckzahl -, sondern wegen der Dreiecke, die die Grafikkarte bei jedem
#: Drehen der Kamera neu zeichnen muss. Fuenfzigtausend Pakete sind dreihundert
#: tausend Vierecke; das Drehen wird zaeh.
#:
#: Zu sehen waere davon ohnehin fast nichts: in einem geschlossenen Stapel ist
#: jedes Paket im Inneren von seinen Nachbarn verdeckt. Oberhalb der Grenze
#: wird deshalb nur die Huelle gezeichnet - die Pakete am Rand einer Lage sowie
#: die oberste Lage. Das Bild ist dasselbe, die Zahl der Koerper faellt um eine
#: Groessenordnung. Dass gefiltert wurde, steht in der Beschriftung der Szene.
MAX_RENDERED_BOXES = 4000


class PyVistaScene:
    """3D-Szene der Palette."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self._plotter = QtInteractor(parent)
        self._plotter.set_background(PALETTE.canvas)
        self._result: PalletResult | None = None
        self._visible: set[int] | None = None
        self._stale = False
        self._show_placeholder()

    # Scene3D ------------------------------------------------------------------

    def widget(self) -> QWidget:
        return self._plotter.interactor

    def set_result(self, result: PalletResult | None) -> None:
        self._result = result
        self._visible = None
        self._rebuild()

    def set_visible_layers(self, indices: set[int] | None) -> None:
        self._visible = indices
        self._rebuild()

    def set_stale(self, stale: bool) -> None:
        self._stale = stale
        self._rebuild()

    def reset_camera(self) -> None:
        self._plotter.reset_camera()
        self._plotter.view_isometric()

    def shutdown(self) -> None:
        """VTK haelt eigene Fenster- und Renderressourcen. Ohne dieses
        Aufraeumen bleibt beim Schliessen der Anwendung ein Prozess haengen."""
        try:
            self._plotter.close()
        except Exception:
            # Beim Beenden ist ein gescheitertes Aufraeumen kein Grund, den
            # Schliessvorgang abzubrechen - das Fenster geht ohnehin zu.
            pass

    # Aufbau -------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        self._plotter.clear()
        self._plotter.add_text(
            "Noch kein Ergebnis", position="upper_left", font_size=10, color=PALETTE.text_muted
        )
        self._plotter.view_isometric()

    def _rebuild(self) -> None:
        self._plotter.clear()
        result = self._result
        if result is None or not result.layers:
            self._show_placeholder()
            self._plotter.render()
            return

        self._add_pallet(result)
        drawn = self._add_packages(result)

        caption = (
            str(result.total_count) + " Pakete, " + str(result.layer_count) + " Lagen, "
            + format(result.total_height_mm, ".0f") + " mm"
        )
        if drawn < result.total_count:
            caption += "   (nur die " + str(drawn) + " sichtbaren Pakete gezeichnet)"
        if self._stale:
            caption += "   (VERALTET)"
        self._plotter.add_text(
            caption, position="upper_left", font_size=9,
            color=PALETTE.stale if self._stale else PALETTE.text_muted,
        )
        self._plotter.add_axes()
        self._plotter.view_isometric()
        self._plotter.reset_camera()
        self._plotter.render()

    #: Eckpunkte eines Einheitswuerfels, als Vielfache der Kantenlaengen.
    _CORNERS = np.array([
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ], dtype=np.float64)

    #: Die sechs Seitenflaechen, als Eckpunktindizes des Einheitswuerfels.
    _FACES = np.array([
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ], dtype=np.int64)

    @classmethod
    def _boxes_to_mesh(cls, boxes: list[tuple[float, float, float, float, float, float]]):
        """Baut ein einziges Netz aus vielen Quadern.

        Der naheliegende Weg - je Paket ein pv.Cube und anschliessend merge -
        kostet bei achttausend Quadern ueber dreissig Sekunden: jeder Aufruf
        legt ein eigenes VTK-Objekt an, und das Zusammenfuehren kopiert immer
        wieder alles. Hier entstehen Eckpunkte und Flaechen stattdessen in zwei
        numpy-Operationen, unabhaengig von der Stueckzahl. Aus Sekunden werden
        Millisekunden.
        """
        origins = np.array([(b[0], b[1], b[2]) for b in boxes], dtype=np.float64)
        sizes = np.array([(b[3], b[4], b[5]) for b in boxes], dtype=np.float64)
        count = len(boxes)

        points = (origins[:, None, :] + cls._CORNERS[None, :, :] * sizes[:, None, :]).reshape(-1, 3)

        offsets = (np.arange(count, dtype=np.int64) * 8)[:, None, None]
        quads = cls._FACES[None, :, :] + offsets                       # (count, 6, 4)
        sides = np.full((count, 6, 1), 4, dtype=np.int64)              # Eckenzahl je Flaeche
        faces = np.concatenate([sides, quads], axis=2).reshape(-1)

        return pv.PolyData(points, faces)

    def _add_pallet(self, result: PalletResult) -> None:
        pallet = result.pallet
        deck = pv.Cube(
            center=(pallet.usable_length_mm / 2.0, pallet.usable_width_mm / 2.0, -pallet.deck_height_mm / 2.0),
            x_length=pallet.usable_length_mm,
            y_length=pallet.usable_width_mm,
            z_length=max(1.0, pallet.deck_height_mm),
        )
        self._plotter.add_mesh(deck, color=PALETTE.pallet_fill, opacity=0.95, show_edges=True,
                               edge_color=PALETTE.pallet_edge)

    @staticmethod
    def _visible_shell(layer: Layer, is_top_layer: bool) -> tuple:
        """Die von aussen sichtbaren Pakete einer Lage.

        Sichtbar ist, was den Rand der Lage beruehrt - und in der obersten Lage
        alles, weil man von oben hineinsieht. Was dazwischen liegt, ist von
        Nachbarn verdeckt und traegt nichts zum Bild bei.
        """
        if is_top_layer or not layer.placements:
            return layer.placements
        min_x = min(p.x_mm for p in layer.placements)
        min_y = min(p.y_mm for p in layer.placements)
        max_x = max(p.right_mm for p in layer.placements)
        max_y = max(p.top_mm for p in layer.placements)
        return tuple(
            p for p in layer.placements
            if abs(p.x_mm - min_x) < 1e-6 or abs(p.right_mm - max_x) < 1e-6
            or abs(p.y_mm - min_y) < 1e-6 or abs(p.top_mm - max_y) < 1e-6
        )

    def _add_packages(self, result: PalletResult) -> int:
        """Zeichnet die Pakete. Gibt zurueck, wie viele gezeichnet wurden."""
        status_by_index = {
            entry.package_index: entry.status for entry in result.load.per_package
        } if result.load.checked else {}

        shown_layers = [
            layer for layer in result.layers
            if self._visible is None or layer.index in self._visible
        ]
        total = sum(layer.count for layer in shown_layers)
        shell_only = total > MAX_RENDERED_BOXES
        top_index = max((layer.index for layer in shown_layers), default=-1)

        # Alle Pakete einer Farbe werden zu einem Netz zusammengefasst. Einzeln
        # gezeichnet braucht eine volle Europalette ueber tausend Akteure, und
        # die Darstellung wird zaeh; zusammengefasst bleibt sie fluessig.
        blocks: dict[str, list] = {}
        drawn = 0
        for layer in shown_layers:
            placements = (
                self._visible_shell(layer, layer.index == top_index) if shell_only
                else layer.placements
            )
            for placement in placements:
                drawn += 1
                status = status_by_index.get(placement.package_index, LoadStatus.OK)
                color = _STATUS_COLORS.get(status, PALETTE.package_fill)
                if status is LoadStatus.OK and placement.rotated:
                    color = PALETTE.package_rotated_fill
                blocks.setdefault(color, []).append((
                    placement.x_mm, placement.y_mm, placement.z_mm,
                    placement.length_mm, placement.width_mm, placement.height_mm,
                ))

        # Kanten nur zeichnen, solange sie zu erkennen sind. Bei tausenden
        # Quadern verschmelzen sie zu einer schwarzen Flaeche und kosten
        # zusaetzlich Zeichenzeit.
        show_edges = drawn <= 1500
        for color, boxes in blocks.items():
            self._plotter.add_mesh(
                self._boxes_to_mesh(boxes), color=color, show_edges=show_edges,
                edge_color=PALETTE.package_edge, opacity=1.0, line_width=1,
            )
        return drawn

    # Zusatz -------------------------------------------------------------------

    def screenshot(self) -> np.ndarray | None:
        """Abbild der Szene - fuer einen spaeteren Bericht."""
        try:
            return self._plotter.screenshot(return_img=True)
        except Exception:
            return None
