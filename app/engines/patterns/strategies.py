"""Die Musterstrategien.

Portiert und ueberarbeitet aus dem Projekt PalletOptimization
(src/palletopt/optimization/heuristic_packer.py und pattern_2d.py). Geaendert
gegenueber dem Original:

* Das Muster arbeitet auf einem beliebigen Rechteck statt auf einer Palette -
  dadurch ist es fuer die Vakuumplatte mitverwendbar (Spezifikation 18).
* Spaltmasse werden durchgaengig beruecksichtigt.
* Die Ausgabe ist stabil sortiert, damit zwei Laeufe identisch sind
  (Spezifikation 39).
* Die im Original nur im Docstring erwaehnten Naeherungen werden als notes
  zurueckgegeben und landen sichtbar in der Oberflaeche (Spezifikation 25).

Zu Schachbrett, Windrad, Spirale und Randverband: diese Muster mischen zwei
Ausrichtungen innerhalb einer Lage. Feldweise - also von Paket zu Paket -
wechseln laesst sich die Ausrichtung nur bei quadratischer Grundflaeche ohne
Luecke. Bei einem Paket 400 x 300 ist die eine Ausrichtung 400 mm hoch, die
andere 300 mm; nebeneinander im selben Band blieben zwangslaeufig 100 mm frei.

Solche Hohlraeume sind kein Schoenheitsfehler: die Ladung verrutscht darin beim
Transport. Deshalb wechselt die Ausrichtung bei rechteckigen Paketen bandweise
(siehe base.alternating_bands) - jedes Band besteht aus vollen Reihen einer
Ausrichtung, die Baender liegen unmittelbar aufeinander, und zwischen zwei
Paketen bleibt nie Platz. Frei bleibt allenfalls ein Streifen am Aussenrand,
und der ist bei keiner Paketgroesse zu vermeiden.

Bei quadratischen Paketen bleibt der feldweise Wechsel erhalten - dort geht er
exakt auf und ergibt das bekannte Bild.

Ausnahme ist der Ringstapel: sein freier Kern ist die Definition des Musters,
nicht ein Mangel. Wer eine geschlossene Lage will, waehlt den Randverband.
"""

from __future__ import annotations

import math

from app.dto.common import Footprint
from app.engines.patterns.base import (
    PatternLayout,
    PatternRequest,
    alternating_bands,
    center_in_bounds,
    register,
    sort_footprints,
)

def _grid(request: PatternRequest, item_l: float, item_w: float, rotated: bool,
          origin_x: float = 0.0, origin_y: float = 0.0,
          span_l: float | None = None, span_w: float | None = None) -> list[Footprint]:
    """Volle Reihen und Spalten eines Rasters innerhalb eines Bereichs."""
    cell_l = item_l + request.gap_mm
    cell_w = item_w + request.gap_mm
    if cell_l <= 0 or cell_w <= 0:
        return []
    available_l = (span_l if span_l is not None else request.bounds_length_mm) + request.gap_mm
    available_w = (span_w if span_w is not None else request.bounds_width_mm) + request.gap_mm
    columns = int(math.floor(available_l / cell_l + 1e-9))
    rows = int(math.floor(available_w / cell_w + 1e-9))
    return [
        Footprint(origin_x + c * cell_l, origin_y + r * cell_w, item_l, item_w, rotated)
        for r in range(rows)
        for c in range(columns)
    ]


def _better(a: list[Footprint], b: list[Footprint]) -> list[Footprint]:
    """Die dichtere von zwei Varianten. Bei Gleichstand gewinnt die erste -
    damit ist die Wahl deterministisch und nicht von der Reihenfolge abhaengig."""
    return a if len(a) >= len(b) else b


# Raster -----------------------------------------------------------------------

@register("uniform_grid")
def uniform_grid(request: PatternRequest) -> PatternLayout:
    """Reines Raster in einer Ausrichtung, nur volle Reihen.

    Die regelmaessigste Lage: jedes Paket steht gleich, keine angebrochenen
    Reihen. Das gibt den besten Lagenverbund nach oben, kostet aber gegenueber
    der dichtesten Packung meist ein paar Pakete.
    """
    upright = _grid(request, request.item_length_mm, request.item_width_mm, False)
    crosswise = _grid(request, request.item_width_mm, request.item_length_mm, True)
    layout = PatternLayout(footprints=sort_footprints(_better(upright, crosswise)))
    return center_in_bounds(layout, request)


def _guillotine(request: PatternRequest, primary_l: float, primary_w: float, rotated: bool) -> list[Footprint]:
    """Hauptraster plus zwei gedrehte Reststreifen (rechts und oben).

    Der klassische Zwei-Schnitt-Guillotineansatz: was das Hauptraster uebrig
    laesst, wird mit der um 90 Grad gedrehten Ausrichtung nachgefuellt.
    """
    gap = request.gap_mm
    cell_l, cell_w = primary_l + gap, primary_w + gap
    other_l, other_w = primary_w, primary_l
    other_cell_l, other_cell_w = other_l + gap, other_w + gap

    if cell_l <= 0 or cell_w <= 0:
        return []

    columns = int(math.floor((request.bounds_length_mm + gap) / cell_l + 1e-9))
    rows = int(math.floor((request.bounds_width_mm + gap) / cell_w + 1e-9))
    placements = [
        Footprint(c * cell_l, r * cell_w, primary_l, primary_w, rotated)
        for r in range(rows)
        for c in range(columns)
    ]

    used_l = columns * cell_l
    used_w = rows * cell_w

    # Reststreifen rechts, begrenzt auf das vom Hauptraster belegte Reihenband.
    remaining_l = request.bounds_length_mm + gap - used_l
    if other_cell_l > 0 and other_cell_w > 0 and remaining_l >= other_cell_l - 1e-9:
        extra_columns = int(math.floor(remaining_l / other_cell_l + 1e-9))
        extra_rows = int(math.floor(used_w / other_cell_w + 1e-9))
        placements.extend(
            Footprint(used_l + c * other_cell_l, r * other_cell_w, other_l, other_w, not rotated)
            for r in range(extra_rows)
            for c in range(extra_columns)
        )

    # Reststreifen oben, ueber die volle Laenge.
    remaining_w = request.bounds_width_mm + gap - used_w
    if other_cell_l > 0 and other_cell_w > 0 and remaining_w >= other_cell_w - 1e-9:
        extra_columns = int(math.floor((request.bounds_length_mm + gap) / other_cell_l + 1e-9))
        extra_rows = int(math.floor(remaining_w / other_cell_w + 1e-9))
        placements.extend(
            Footprint(c * other_cell_l, used_w + r * other_cell_w, other_l, other_w, not rotated)
            for r in range(extra_rows)
            for c in range(extra_columns)
        )

    return placements


@register("guillotine_mix")
def guillotine_mix(request: PatternRequest) -> PatternLayout:
    """Hauptraster mit gedrehten Reststreifen - Mittelweg aus Dichte und Ordnung."""
    upright = _guillotine(request, request.item_length_mm, request.item_width_mm, False)
    crosswise = _guillotine(request, request.item_width_mm, request.item_length_mm, True)
    layout = PatternLayout(footprints=sort_footprints(_better(upright, crosswise)))
    return center_in_bounds(layout, request)


# Verbaende --------------------------------------------------------------------

@register("running_bond")
def running_bond(request: PatternRequest) -> PatternLayout:
    """Laeuferverband: jede zweite Reihe um eine halbe Elementlaenge versetzt.

    Gesetzt werden nur vollstaendige Elemente - am versetzten Reihenende bleibt
    eine halbe Elementlaenge frei. Genau das macht den Verband aus: die Stoesse
    der Reihen liegen nicht uebereinander.
    """

    def rows_for(item_l: float, item_w: float, rotated: bool) -> list[Footprint]:
        gap = request.gap_mm
        cell_l, cell_w = item_l + gap, item_w + gap
        if cell_l <= 0 or cell_w <= 0:
            return []
        rows = int(math.floor((request.bounds_width_mm + gap) / cell_w + 1e-9))
        placements: list[Footprint] = []
        for r in range(rows):
            offset = cell_l / 2.0 if r % 2 == 1 else 0.0
            x = offset
            while x + item_l <= request.bounds_length_mm + 1e-9:
                placements.append(Footprint(x, r * cell_w, item_l, item_w, rotated))
                x += cell_l
        return placements

    upright = rows_for(request.item_length_mm, request.item_width_mm, False)
    crosswise = rows_for(request.item_width_mm, request.item_length_mm, True)
    layout = PatternLayout(footprints=sort_footprints(_better(upright, crosswise)))
    return center_in_bounds(layout, request)


def _is_square_item(request: PatternRequest) -> bool:
    """Ob das Paket quadratisch ist - nur dann geht ein feldweiser Wechsel auf."""
    return abs(request.item_length_mm - request.item_width_mm) < 1e-9


def _square_field_layout(request: PatternRequest, rotated_for_field) -> PatternLayout:
    """Feldweise wechselndes Muster auf einem Quadratraster.

    Nur fuer quadratische Pakete. Dort sind beide Ausrichtungen gleich gross,
    das Raster geht ohne Rest auf, und der Wechsel ist tatsaechlich feldweise
    sichtbar - ein echtes Schachbrett.
    """
    cell = request.item_length_mm + request.gap_mm
    if cell <= 0:
        return PatternLayout()
    columns = int((request.bounds_length_mm + request.gap_mm) // cell)
    rows = int((request.bounds_width_mm + request.gap_mm) // cell)
    item = request.item_length_mm
    footprints = [
        Footprint(column * cell, row * cell, item, item, bool(rotated_for_field(row, column)))
        for row in range(rows)
        for column in range(columns)
    ]
    return center_in_bounds(PatternLayout(sort_footprints(footprints)), request)


#: Hinweis, wenn der feldweise Wechsel nicht moeglich ist.
_BAND_NOTE = (
    "Bei rechteckigem Paket wechselt die Ausrichtung bandweise statt feldweise. "
    "Ein feldweiser Wechsel geht nur bei quadratischer Grundflaeche ohne Luecke "
    "auf - sonst blieben zwischen den Paketen Hohlraeume, und die Ladung wuerde "
    "verrutschen. So liegt Paket an Paket."
)


@register("checkerboard")
def checkerboard(request: PatternRequest) -> PatternLayout:
    """Schachbrett: die Ausrichtung wechselt abwechselnd.

    Bei quadratischem Paket feldweise - das ist das klassische Schachbrett und
    geht exakt auf. Sonst bandweise, damit keine Luecken entstehen.
    """
    if _is_square_item(request):
        return _square_field_layout(request, lambda row, column: (row + column) % 2 == 1)
    return alternating_bands(request, lambda index: index % 2 == 1, _BAND_NOTE)


@register("pinwheel")
def pinwheel(request: PatternRequest) -> PatternLayout:
    """Windrad: die Ausrichtung wechselt in Zweiergruppen.

    Bei quadratischem Paket entsteht das bekannte Bild aus vier Quadranten mit
    ueber Kreuz wechselnder Ausrichtung. Sonst wechseln jeweils zwei Baender
    gemeinsam - der Verband bleibt grob erkennbar, die Lage bleibt lueckenlos.

    Eine fortlaufende Drehung ist mit achsparallelen Rechtecken ohnehin nicht
    darstellbar; jede Umsetzung ist eine Annaeherung.
    """
    if _is_square_item(request):
        cell = request.item_length_mm + request.gap_mm
        columns = int((request.bounds_length_mm + request.gap_mm) // cell) if cell > 0 else 0
        rows = int((request.bounds_width_mm + request.gap_mm) // cell) if cell > 0 else 0
        half_column, half_row = columns / 2.0, rows / 2.0
        return _square_field_layout(
            request,
            lambda row, column: (column < half_column) != (row < half_row),
        )
    return alternating_bands(request, lambda index: (index // 2) % 2 == 1, _BAND_NOTE)


@register("spiral")
def spiral(request: PatternRequest) -> PatternLayout:
    """Spiralverband: die Ausrichtung wechselt von aussen nach innen.

    Bei quadratischem Paket ringweise um die Mitte, sonst bandweise von aussen
    nach innen - das aeusserste und das innerste Band liegen gleich, die
    dazwischen wechseln.
    """
    if _is_square_item(request):
        cell = request.item_length_mm + request.gap_mm
        columns = int((request.bounds_length_mm + request.gap_mm) // cell) if cell > 0 else 0
        rows = int((request.bounds_width_mm + request.gap_mm) // cell) if cell > 0 else 0
        return _square_field_layout(
            request,
            lambda row, column: min(row, column, rows - 1 - row, columns - 1 - column) % 2 == 1,
        )

    # Ohne Quadratraster ist die Bandzahl vorab nicht bekannt; geschaetzt wird
    # sie aus der kleineren Paketkante, was fuer die Ringzaehlung genuegt.
    smaller = min(request.item_length_mm, request.item_width_mm) + request.gap_mm
    bands = max(1, int((request.bounds_width_mm + request.gap_mm) // smaller)) if smaller > 0 else 1
    return alternating_bands(
        request, lambda index: min(index, bands - 1 - index) % 2 == 1, _BAND_NOTE
    )


def _ring_layout(request: PatternRequest, hollow: bool) -> PatternLayout:
    """Randverband und Ringstapel.

    Der Randverband ist eine Vollflaeche: aeusserste Baender in einer, innere in
    der anderen Ausrichtung. Der Ringstapel dagegen laesst den Kern ausdruecklich
    frei - das ist die Definition des Musters, nicht ein Mangel.
    """
    if not hollow:
        smaller = min(request.item_length_mm, request.item_width_mm) + request.gap_mm
        bands = max(1, int((request.bounds_width_mm + request.gap_mm) // smaller)) if smaller > 0 else 1
        return alternating_bands(
            request,
            lambda index: not (index == 0 or index >= bands - 1),
            _BAND_NOTE if not _is_square_item(request) else "",
        )

    cell = max(request.item_length_mm, request.item_width_mm) + request.gap_mm
    columns = int((request.bounds_length_mm + request.gap_mm) // cell) if cell > 0 else 0
    rows = int((request.bounds_width_mm + request.gap_mm) // cell) if cell > 0 else 0
    notes: tuple[str, ...] = (
        "Ringstapel: der Kern bleibt ausdruecklich frei. Fuer eine geschlossene "
        "Lage ist der Randverband zu waehlen.",
    )
    if rows <= 2 or columns <= 2:
        notes = notes + ("Raster zu klein fuer einen freien Kern - die Lage ist vollstaendig gefuellt.",)

    footprints: list[Footprint] = []
    inner = cell - request.gap_mm
    for row in range(rows):
        for column in range(columns):
            on_border = row in (0, rows - 1) or column in (0, columns - 1)
            if not on_border and rows > 2 and columns > 2:
                continue
            rotated = not on_border
            item_l = request.item_width_mm if rotated else request.item_length_mm
            item_w = request.item_length_mm if rotated else request.item_width_mm
            footprints.append(Footprint(
                column * cell + (inner - item_l) / 2.0,
                row * cell + (inner - item_w) / 2.0,
                item_l, item_w, rotated,
            ))

    return center_in_bounds(PatternLayout(sort_footprints(footprints), notes), request)


@register("perimeter")
def perimeter(request: PatternRequest) -> PatternLayout:
    """Randverband: aeussere Baender in einer, Kern in der anderen Ausrichtung."""
    return _ring_layout(request, hollow=False)


@register("ring")
def ring(request: PatternRequest) -> PatternLayout:
    """Ringstapel: geschlossener Aussenring, Kern bleibt frei."""
    return _ring_layout(request, hollow=True)


@register("column")
def column(request: PatternRequest) -> PatternLayout:
    """Saeulenraster - geometrisch identisch zum reinen Raster.

    Eigene Kennung, weil sich Saeulen- und Blockstapel erst durch den Z-Modus
    unterscheiden: dieselbe Lage, einmal deckungsgleich wiederholt, einmal
    gespiegelt. Die Musterkonfiguration kann beide getrennt anbieten, ohne dass
    die Strategie es wissen muss.
    """
    return uniform_grid(request)


@register("max_count")
def max_count(request: PatternRequest) -> PatternLayout:
    """Dichteste Packung aus den generischen Strategien.

    Der optionale CP-SAT-Loeser wird nur einbezogen, wenn er verfuegbar und in
    den Optionen freigegeben ist - siehe app/engines/patterns/solver.py. Ohne
    ihn ist das Ergebnis das beste aus Raster und Guillotine.
    """
    candidates = [uniform_grid(request), guillotine_mix(request), running_bond(request)]

    if request.options.get("use_solver"):
        from app.engines.patterns.solver import solve_max_count

        solved = solve_max_count(request)
        if solved is not None:
            candidates.append(solved)

    best = max(candidates, key=lambda layout: (layout.count, layout.used_area_mm2))
    return best


@register("auto")
def auto(request: PatternRequest) -> PatternLayout:
    """Wie max_count - eigene Kennung fuer die Auswahl 'Automatisch'."""
    return max_count(request)
