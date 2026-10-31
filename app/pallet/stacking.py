"""Wie aus Lagen ein Stapel wird - und was das fuer die Pakete bedeutet.

Zwei Schritte derselben Frage, deshalb an einem Ort:

    stacking   setzt die Lagen uebereinander und bestimmt die Hoehen
    loads      rechnet aus, welches Paket wieviel Auflast traegt

Zusammengelegt aus engines/palletizing/{stacking,loads}.py.
"""

from __future__ import annotations

from app.domain.geometry import Footprint
from app.domain.package import Orientation
from app.pallet.models import Layer, Placement, ZMode
from app.pallet.models import Layer, LoadAnalysis, LoadStatus, PackageLoad, Placement


# ---------------------------------------------------------------------------
# stacking.py
# ---------------------------------------------------------------------------
"""Aufbau des Stapels aus einer fertigen Grundlage.

Die Grundlage kommt aus der Musterschicht und ist bereits zentriert. Hier wird
nur noch nach oben wiederholt - in einem der drei Modi aus ZMode.

Warum das Spiegeln um die eigene Mitte und nicht um den Palettenursprung
geschieht: eine zentrierte Lage soll nach dem Spiegeln zentriert bleiben. Wuerde
um den Ursprung gespiegelt, wanderte jede zweite Lage an den gegenueberliegenden
Rand, und der Stapel bekaeme eine Schraeglage statt eines Verbunds.
"""

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


# ---------------------------------------------------------------------------
# loads.py
# ---------------------------------------------------------------------------
"""Belastung der einzelnen Pakete im Stapel.

Spezifikation 12.3 beschreibt die Regel als "so viele Pakete darueber":

    oberste Lage      0 Pakete darueber
    zweite Lage       1 Paket darueber
    dritte Lage       2 Pakete darueber

Das stimmt exakt fuer den Saeulenstapel, in dem jedes Paket genau auf dem
darunter steht. Sobald ein Verband im Spiel ist, stimmt es nicht mehr: ein
gespiegeltes oder gedrehtes Paket liegt auf zwei oder vier Nachbarn auf und gibt
seine Last anteilig weiter. Das ist der eigentliche Zweck eines Verbands.

Gerechnet wird deshalb kaskadierend von oben nach unten: jedes Paket gibt sein
Eigengewicht plus alles, was es bereits traegt, an die Pakete darunter weiter -
im Verhaeltnis der Ueberdeckung der Standflaechen. Portiert aus
PalletOptimization (analysis/load_pressure.py).

Grenzen des Modells, ausdruecklich benannt: Brueckenbildung und Steifigkeit der
Kartons bleiben unberuecksichtigt. Eine Kiste, die zwischen zwei Nachbarn
spannt, traegt in Wirklichkeit anders. Das zu rechnen erforderte eine
Strukturanalyse; die Naeherung ist die uebliche statische Annahme und wird im
Trace als solche vermerkt.
"""

WARNING_THRESHOLD_PCT = 80.0
CRITICAL_THRESHOLD_PCT = 100.0
CRITICAL_TOLERANCE_PCT = 1e-6


def _neighbour_index(placements: tuple, cell_mm: float) -> dict[tuple[int, int], list]:
    """Rasterindex ueber die Standflaechen einer Lage.

    Ohne ihn vergleicht die Kaskade jedes Paket mit jedem darunter. Bei 2400
    Paketen je Lage und 80 Lagen sind das ueber vierhundert Millionen
    Ueberdeckungspruefungen - gemessene fuenfundsiebzig Sekunden fuer eine
    einzige Palette. Mit dem Index werden nur die Nachbarn geprueft, die
    ueberhaupt in Frage kommen; der Aufwand faellt von quadratisch auf linear.
    """
    index: dict[tuple[int, int], list] = {}
    if cell_mm <= 0.0:
        return index
    for placement in placements:
        x0 = int(placement.x_mm // cell_mm)
        x1 = int((placement.right_mm - 1e-9) // cell_mm)
        y0 = int(placement.y_mm // cell_mm)
        y1 = int((placement.top_mm - 1e-9) // cell_mm)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                index.setdefault((gx, gy), []).append(placement)
    return index


def _candidates_below(index: dict, placement: Placement, cell_mm: float) -> list:
    """Die Pakete der Lage darunter, die diese Standflaeche beruehren koennen."""
    if cell_mm <= 0.0:
        return []
    seen: set[int] = set()
    found: list = []
    x0 = int(placement.x_mm // cell_mm)
    x1 = int((placement.right_mm - 1e-9) // cell_mm)
    y0 = int(placement.y_mm // cell_mm)
    y1 = int((placement.top_mm - 1e-9) // cell_mm)
    for gx in range(x0, x1 + 1):
        for gy in range(y0, y1 + 1):
            for candidate in index.get((gx, gy), ()):
                if candidate.package_index not in seen:
                    seen.add(candidate.package_index)
                    found.append(candidate)
    return found


def analyze(layers: tuple[Layer, ...], max_stack_load_kg: float) -> LoadAnalysis:
    """Berechnet die Auflast je Paket.

    Ohne zulaessige Stapellast entfaellt die Rechnung ganz: es gaebe keinen
    Grenzwert, gegen den die Zahlen zu vergleichen waeren, und bei grossen
    Stapeln kostet die Kaskade spuerbar Zeit. checked bleibt dann False, und
    die Oberflaeche zeigt "nicht geprueft" statt einer Ampel ohne Grundlage.
    """
    if max_stack_load_kg <= 0.0:
        return LoadAnalysis(checked=False)

    ordered = sorted(layers, key=lambda layer: layer.index)
    carried: dict[int, float] = {}
    for layer in ordered:
        for placement in layer.placements:
            carried[placement.package_index] = 0.0

    for position in range(len(ordered) - 1, 0, -1):
        upper = ordered[position].placements
        lower = ordered[position - 1].placements
        if not lower:
            continue

        cell_mm = max(max(p.length_mm, p.width_mm) for p in lower)
        index = _neighbour_index(lower, cell_mm)

        for above in upper:
            downward = above.weight_kg + carried[above.package_index]
            overlaps = [
                (below, below.overlap_area_mm2(above))
                for below in _candidates_below(index, above, cell_mm)
            ]
            total = sum(area for _, area in overlaps)
            if total <= 0.0:
                # Kein Nachbar darunter: die Last geht direkt auf die Palette.
                # Das kommt bei Mustern mit freiem Kern vor.
                continue
            for below, area in overlaps:
                if area > 0.0:
                    carried[below.package_index] += downward * (area / total)

    results: list[PackageLoad] = []
    max_pct = 0.0
    critical = 0
    warning = 0

    for layer in ordered:
        for placement in layer.placements:
            supported = carried[placement.package_index]
            pct = supported / max_stack_load_kg * 100.0
            if pct > CRITICAL_THRESHOLD_PCT + CRITICAL_TOLERANCE_PCT:
                status = LoadStatus.CRITICAL
                critical += 1
            elif pct >= WARNING_THRESHOLD_PCT:
                status = LoadStatus.WARNING
                warning += 1
            else:
                status = LoadStatus.OK
            results.append(
                PackageLoad(
                    package_index=placement.package_index,
                    layer_index=layer.index,
                    supported_weight_kg=supported,
                    max_stack_load_kg=max_stack_load_kg,
                    load_pct=pct,
                    status=status,
                )
            )
            max_pct = max(max_pct, pct)

    return LoadAnalysis(
        per_package=tuple(results),
        max_load_pct=max_pct,
        critical_count=critical,
        warning_count=warning,
        checked=True,
    )


def max_layers_by_stack_load(package_weight_kg: float, max_stack_load_kg: float) -> int:
    """Schranke fuer die Lagenzahl aus der Stapellast - die Saeulenrechnung.

    Im Saeulenstapel steht jedes Paket genau auf dem darunter, das unterste
    traegt also (n-1) Pakete. Das ist die Rechnung aus Spezifikation 12.3.

    Sie ist ausdruecklich NUR eine erste Schranke, keine Garantie. Naheliegend
    waere die Annahme, ein Verband verteile die Last immer besser und die
    Schranke sei deshalb stets sicher - das stimmt nicht. Im Laeuferverband
    liegt ein Paket unter Umstaenden zum groessten Teil auf einem einzigen
    Nachbarn; dieser traegt dann mehr als im Saeulenstapel, wo sich die Last
    sauber auf Saeulen verteilt. Ein Verband verbessert den Zusammenhalt, nicht
    zwangslaeufig die Punktlast.

    Deshalb rechnet der Optimierer anschliessend die tatsaechliche Kaskade und
    kuerzt den Stapel, wenn dabei ein Paket ueberlastet wird.
    """
    if max_stack_load_kg <= 0.0 or package_weight_kg <= 0.0:
        return 0  # 0 bedeutet hier: keine Begrenzung durch die Stapellast
    return int(max_stack_load_kg // package_weight_kg) + 1
