"""Aufbau des Stapels aus einer fertigen Grundlage.

Die Grundlage kommt aus der Musterschicht und ist bereits zentriert. Hier wird
nur noch nach oben wiederholt - in einem der drei Modi aus ZMode.

Warum das Spiegeln um die eigene Mitte und nicht um den Palettenursprung
geschieht: eine zentrierte Lage soll nach dem Spiegeln zentriert bleiben. Wuerde
um den Ursprung gespiegelt, wanderte jede zweite Lage an den gegenueberliegenden
Rand, und der Stapel bekaeme eine Schraeglage statt eines Verbunds.
"""

from __future__ import annotations

from app.dto.common import Footprint
from app.dto.package import Orientation
from app.dto.pallet import Layer, Placement, ZMode


def build_layer(
    footprints: tuple[Footprint, ...],
    index: int,
    z_mm: float,
    height_mm: float,
    weight_kg: float,
    orientation: Orientation,
    bounds_area_mm2: float,
    variant: str,
    first_package_index: int,
) -> Layer:
    """Wandelt Standflaechen in eine Lage aus Platzierungen."""
    placements = tuple(
        Placement(
            package_index=first_package_index + position,
            layer_index=index,
            x_mm=footprint.x_mm,
            y_mm=footprint.y_mm,
            z_mm=z_mm,
            length_mm=footprint.length_mm,
            width_mm=footprint.width_mm,
            height_mm=height_mm,
            rotated=footprint.rotated,
            orientation=orientation,
            weight_kg=weight_kg,
        )
        for position, footprint in enumerate(footprints)
    )
    used = sum(p.footprint_area_mm2 for p in placements)
    utilization = min(1.0, used / bounds_area_mm2) if bounds_area_mm2 > 0 else 0.0
    return Layer(
        index=index,
        z_mm=z_mm,
        height_mm=height_mm,
        placements=placements,
        variant=variant,
        footprint_utilization_ratio=utilization,
    )


def mirror_footprints(footprints: tuple[Footprint, ...]) -> tuple[Footprint, ...]:
    """Drehung der Lage um 180 Grad um ihre eigene Mitte."""
    if not footprints:
        return footprints
    min_x = min(f.x_mm for f in footprints)
    min_y = min(f.y_mm for f in footprints)
    max_x = max(f.x_mm + f.length_mm for f in footprints)
    max_y = max(f.y_mm + f.width_mm for f in footprints)
    return tuple(
        Footprint(
            min_x + max_x - f.x_mm - f.length_mm,
            min_y + max_y - f.y_mm - f.width_mm,
            f.length_mm,
            f.width_mm,
            f.rotated,
        )
        for f in footprints
    )


def repeat(
    base: tuple[Footprint, ...],
    alternate: tuple[Footprint, ...] | None,
    layer_count: int,
    z_mode: ZMode,
    layer_height_mm: float,
    package_weight_kg: float,
    orientation: Orientation,
    bounds_area_mm2: float,
    variant: str,
) -> tuple[Layer, ...]:
    """Baut die Lagen des Stapels.

    Bei ROTATE90 ohne zweite Lage wird gespiegelt statt zu scheitern: der
    Wechselverband braucht eine um 90 Grad gedrehte Variante, und wenn die
    Geometrie keine hergibt, ist der Verband die naechstbeste Wahl. Die
    Abweichung meldet der Optimierer als Warnung.
    """
    layers: list[Layer] = []
    mirrored = mirror_footprints(base)
    package_index = 0

    for index in range(layer_count):
        if index == 0 or z_mode is ZMode.IDENTICAL:
            footprints = base
        elif z_mode is ZMode.ROTATE90:
            if index % 2 == 0:
                footprints = base
            else:
                footprints = alternate if alternate else mirrored
        else:  # MIRROR
            footprints = base if index % 2 == 0 else mirrored

        layer = build_layer(
            footprints=footprints,
            index=index,
            z_mm=index * layer_height_mm,
            height_mm=layer_height_mm,
            weight_kg=package_weight_kg,
            orientation=orientation,
            bounds_area_mm2=bounds_area_mm2,
            variant=variant,
            first_package_index=package_index,
        )
        package_index += layer.count
        layers.append(layer)

    return tuple(layers)


def trim_to_count(layers: tuple[Layer, ...], wanted: int) -> tuple[Layer, ...]:
    """Kuerzt den Stapel auf eine gewuenschte Stueckzahl.

    Gekuerzt wird von oben, und die oberste Lage wird notfalls nur teilweise
    belegt - genau so wird auch in der Praxis palettiert, wenn die letzte Lage
    nicht voll wird.
    """
    if wanted <= 0:
        return layers
    kept: list[Layer] = []
    remaining = wanted
    for layer in layers:
        if remaining <= 0:
            break
        if layer.count <= remaining:
            kept.append(layer)
            remaining -= layer.count
            continue
        placements = layer.placements[:remaining]
        used = sum(p.footprint_area_mm2 for p in placements)
        full_used = sum(p.footprint_area_mm2 for p in layer.placements)
        ratio = (
            layer.footprint_utilization_ratio * used / full_used if full_used > 0 else 0.0
        )
        kept.append(
            Layer(
                index=layer.index,
                z_mm=layer.z_mm,
                height_mm=layer.height_mm,
                placements=placements,
                variant=layer.variant,
                footprint_utilization_ratio=ratio,
            )
        )
        remaining = 0
    return tuple(kept)
