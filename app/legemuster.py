"""Muster, nach denen Pakete in einer Ebene liegen.

Eine Ebene hoeher als die beiden Scheiben, weil BEIDE sie brauchen: die
Palettierung legt damit ihre Lagen, und die Vakuumplatte ordnet damit die
Pakete an, die sie heben soll (Spezifikation 18). Haette jede Scheibe ihre
eigene Musterschicht, waere genau das unmoeglich, was der Benutzer erwartet -
dieselbe Lage auf der Palette und unter der Platte.

Eine Strategie ist eine Funktion plus ein Registryeintrag. Der Import der
Strategien am Ende dieser Datei fuellt die Registry; ohne ihn faende
get_strategy() nichts.

Zusammengelegt aus engines/patterns/{base,strategies,solver}.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol
from app.geometrie import Footprint
import math
import logging


# ---------------------------------------------------------------------------
# base.py
# ---------------------------------------------------------------------------
"""Der Mustervertrag - gemeinsam genutzt von Palettierung und Vakuumplatte.

Spezifikation 18 verlangt, dass die Vakuumplatte ein in der Palettierung
gewaehltes Muster
wiederverwenden kann, ohne die Palettierlogik zu duplizieren. Der Schluessel
dazu steht hier: ein Muster kennt keine Palette. Es fuellt ein Rechteck mit
gleichen Rechtecken. Ob dieses Rechteck eine Palettenflaeche oder eine
Saugerplatte ist, geht es nichts an.

    PatternRequest (Rechteck + Elementmass)
            |
            +--> Palettierung: Palettenflaeche
            |
            +--> Vakuumplatte: Plattenflaeche

Ein neues Muster braucht eine Funktion mit dieser Signatur und einen Eintrag in
der Registry - keinen Eingriff in Optimierer oder Oberflaeche.

Zum Spaltmass: erzeugt wird mit einem um gap_mm vergroesserten Element, platziert
wird das echte Mass an der Zellenecke. Dadurch ist der Abstand zwischen zwei
Nachbarn immer mindestens gap_mm, ohne dass jede Strategie das selbst bedenken
muss.
"""

@dataclass(frozen=True, slots=True)
class PatternRequest:
    """Eingabe eines Musters: fuelle dieses Rechteck mit diesen Elementen."""

    bounds_length_mm: float
    bounds_width_mm: float
    item_length_mm: float
    item_width_mm: float

    #: Lichter Mindestabstand zwischen zwei Elementen.
    gap_mm: float = 0.0

    #: Obergrenze der Stueckzahl. 0 bedeutet: so viele wie hineinpassen.
    max_count: int = 0

    options: dict = field(default_factory=dict)

    @property
    def cell_length_mm(self) -> float:
        """Rastermass in Laengsrichtung, Spalt eingerechnet."""
        return self.item_length_mm + self.gap_mm

    @property
    def cell_width_mm(self) -> float:
        return self.item_width_mm + self.gap_mm

    @property
    def usable_length_mm(self) -> float:
        """Der letzte Nachbar braucht rechts keinen Spalt mehr."""
        return self.bounds_length_mm + self.gap_mm

    @property
    def usable_width_mm(self) -> float:
        return self.bounds_width_mm + self.gap_mm

    def rotated(self) -> PatternRequest:
        """Dieselbe Anfrage mit vertauschten Elementkanten."""
        return PatternRequest(
            bounds_length_mm=self.bounds_length_mm,
            bounds_width_mm=self.bounds_width_mm,
            item_length_mm=self.item_width_mm,
            item_width_mm=self.item_length_mm,
            gap_mm=self.gap_mm,
            max_count=self.max_count,
            options=self.options,
        )


@dataclass(frozen=True, slots=True)
class PatternLayout:
    """Ergebnis eines Musters."""

    footprints: tuple[Footprint, ...] = ()

    #: Getroffene Vereinfachungen, wandern in den Trace und in die Oberflaeche.
    notes: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.footprints)

    @property
    def used_area_mm2(self) -> float:
        return sum(f.length_mm * f.width_mm for f in self.footprints)


class LayerPattern(Protocol):
    """Vertrag eines Musters."""

    pattern_id: str

    def generate(self, request: PatternRequest) -> PatternLayout: ...


#: Eine Strategie ist eine Funktion. Klassen waeren hier nur Verpackung - die
#: Muster haben keinen Zustand.
StrategyFunction = Callable[[PatternRequest], PatternLayout]

_REGISTRY: dict[str, StrategyFunction] = {}


def register(strategy_id: str) -> Callable[[StrategyFunction], StrategyFunction]:
    """Dekorator zur Anmeldung einer Strategie."""

    def decorator(function: StrategyFunction) -> StrategyFunction:
        if strategy_id in _REGISTRY:
            raise ValueError("Strategie '" + strategy_id + "' ist bereits angemeldet")
        _REGISTRY[strategy_id] = function
        return function

    return decorator


def get_strategy(strategy_id: str) -> StrategyFunction | None:
    return _REGISTRY.get(strategy_id)


def available_strategies() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def generate(strategy_id: str, request: PatternRequest) -> PatternLayout:
    """Fuehrt eine Strategie aus. Unbekannte Kennung ist ein Programmfehler,
    kein Benutzerfehler - die Konfiguration wird beim Laden geprueft."""
    strategy = _REGISTRY.get(strategy_id)
    if strategy is None:
        raise KeyError(
            "Unbekannte Musterstrategie '" + strategy_id + "'. Bekannt sind: "
            + ", ".join(available_strategies())
        )
    layout = strategy(request)
    if request.max_count > 0 and layout.count > request.max_count:
        layout = PatternLayout(footprints=layout.footprints[: request.max_count], notes=layout.notes)
    return layout


def center_in_bounds(layout: PatternLayout, request: PatternRequest) -> PatternLayout:
    """Verschiebt das Ergebnis in die Mitte des Rechtecks.

    Ohne Zentrierung klebt die Ladung in einer Ecke: der Schwerpunkt liegt dann
    ausserhalb der Palettenmitte, und auf der Saugerplatte lieber ungleich
    verteilt statt symmetrisch. Beides ist unerwuenscht, kostet aber nur diese
    eine Verschiebung.
    """
    if not layout.footprints:
        return layout
    min_x = min(f.x_mm for f in layout.footprints)
    min_y = min(f.y_mm for f in layout.footprints)
    max_x = max(f.x_mm + f.length_mm for f in layout.footprints)
    max_y = max(f.y_mm + f.width_mm for f in layout.footprints)

    offset_x = (request.bounds_length_mm - (max_x - min_x)) / 2.0 - min_x
    offset_y = (request.bounds_width_mm - (max_y - min_y)) / 2.0 - min_y

    return PatternLayout(
        footprints=tuple(
            Footprint(f.x_mm + offset_x, f.y_mm + offset_y, f.length_mm, f.width_mm, f.rotated)
            for f in layout.footprints
        ),
        notes=layout.notes,
    )


def alternating_bands(
    request: PatternRequest,
    rotated_for_band,
    note: str = "",
) -> PatternLayout:
    """Baut eine Lage aus waagerechten Baendern wechselnder Ausrichtung.

    Das ist die einzige Bauform, die bei beliebigem Seitenverhaeltnis ohne
    Hohlraum auskommt und trotzdem ein Wechselmuster ergibt.

    Der Grund ist geometrisch: innerhalb eines Bandes fester Hoehe passt nur
    eine Ausrichtung. Ein Paket 400 x 300 ist quer 400 mm hoch und laengs
    300 mm - beide nebeneinander in ein Band zu legen liesse zwangslaeufig
    100 mm frei. Ein feldweise wechselndes Schachbrett geht deshalb nur bei
    quadratischen Paketen exakt auf; bei allen anderen entstehen Luecken
    zwischen den Paketen, und die Ladung verrutscht beim Transport.

    Gewechselt wird darum bandweise: jedes Band besteht aus vollen Reihen einer
    Ausrichtung, die Baender liegen unmittelbar aufeinander. Zwischen zwei
    Paketen bleibt nie Platz; frei bleibt allenfalls ein Streifen am aeusseren
    Rand, und der laesst sich nicht vermeiden.

    rotated_for_band(index) sagt, welche Ausrichtung das Band mit dieser
    Nummer bekommt. Damit erzeugen Schachbrett, Spirale und Windrad
    unterschiedliche Wechselfolgen aus derselben Mechanik.

    Passt ein Band in seiner vorgesehenen Ausrichtung nicht mehr, wird die
    andere versucht - so wird der Rest oben noch gefuellt, statt ihn
    liegenzulassen.
    """
    gap = request.gap_mm
    length_mm, width_mm = request.item_length_mm, request.item_width_mm
    if length_mm <= 0 or width_mm <= 0:
        return PatternLayout()

    placements: list[Footprint] = []
    y = 0.0
    index = 0

    while True:
        wanted = bool(rotated_for_band(index))
        chosen: tuple[float, float, bool] | None = None
        for rotated in (wanted, not wanted):
            item_l = width_mm if rotated else length_mm
            item_w = length_mm if rotated else width_mm
            if y + item_w <= request.bounds_width_mm + 1e-9 and item_l <= request.bounds_length_mm + 1e-9:
                chosen = (item_l, item_w, rotated)
                break
        if chosen is None:
            break

        item_l, item_w, rotated = chosen
        cell_l = item_l + gap
        columns = int((request.bounds_length_mm + gap) // cell_l) if cell_l > 0 else 0
        if columns <= 0:
            break

        placements.extend(
            Footprint(column * cell_l, y, item_l, item_w, rotated) for column in range(columns)
        )
        y += item_w + gap
        index += 1

    notes = (note,) if note else ()
    return center_in_bounds(PatternLayout(sort_footprints(placements), notes), request)


def sort_footprints(footprints: list[Footprint]) -> tuple[Footprint, ...]:
    """Stabile Reihenfolge: erst nach y, dann nach x.

    Spezifikation 39 verlangt reproduzierbare Ergebnisse. Die Strategien
    erzeugen ihre Platzierungen in unterschiedlicher Reihenfolge; eine feste
    Sortierung macht zwei Laeufe byteweise vergleichbar und die 2D-Ansicht
    von Lauf zu Lauf stabil.
    """
    return tuple(sorted(footprints, key=lambda f: (round(f.y_mm, 6), round(f.x_mm, 6), f.rotated)))


# ---------------------------------------------------------------------------
# strategies.py
# ---------------------------------------------------------------------------
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
    den Optionen freigegeben ist - siehe app/legemuster.py. Ohne
    ihn ist das Ergebnis das beste aus Raster und Guillotine.
    """
    candidates = [uniform_grid(request), guillotine_mix(request), running_bond(request)]

    if request.options.get("use_solver"):
        from app.legemuster import solve_max_count

        solved = solve_max_count(request)
        if solved is not None:
            candidates.append(solved)

    best = max(candidates, key=lambda layout: (layout.count, layout.used_area_mm2))
    return best


@register("auto")
def auto(request: PatternRequest) -> PatternLayout:
    """Wie max_count - eigene Kennung fuer die Auswahl 'Automatisch'."""
    return max_count(request)


# ---------------------------------------------------------------------------
# solver.py
# ---------------------------------------------------------------------------
"""Optionale Verdichtung per CP-SAT.

Der Loeser ist ausdruecklich eine Zusatzstrategie, keine Voraussetzung. Fehlt
ortools, arbeitet die Anwendung vollstaendig weiter - max_count nimmt dann das
beste Ergebnis der Heuristiken.

Zwei Aenderungen gegenueber dem Original in PalletOptimization, ohne die
Spezifikation 39 nicht einzuhalten waere:

* num_search_workers = 1. Mit mehreren Suchfaeden haengt das Ergebnis davon ab,
  welcher Faden zuerst fertig wird - zwei Laeufe mit identischer Eingabe koennen
  unterschiedliche Anordnungen liefern.
* max_deterministic_time statt max_time_in_seconds. Ein Zeitlimit nach Uhr
  bricht je nach Auslastung der Maschine an anderer Stelle ab. Das
  deterministische Limit zaehlt Rechenschritte und liefert deshalb auf jedem
  Rechner dasselbe Ergebnis.

Beides kostet Loesungsqualitaet. Reproduzierbarkeit ist hier wichtiger: ein
Palettierplan, der beim zweiten Aufruf anders aussieht, ist als Arbeitsunterlage
wertlos.
"""

logger = logging.getLogger(__name__)

#: Ab dieser geschaetzten Stueckzahl lohnt der Loeser nicht mehr - die
#: Modellgroesse waechst mit der Zahl der Kandidatenkoerper, die Heuristik ist
#: dann sowohl schneller als auch praktisch gleich gut.
LARGE_INSTANCE_THRESHOLD = 120

#: Deterministisches Rechenbudget. Die Einheit sind interne Arbeitsschritte,
#: nicht Sekunden.
DETERMINISTIC_LIMIT = 8.0


def solver_available() -> bool:
    """Ob ortools installiert ist. Wird auch von der Oberflaeche gefragt, um
    die Option auszugrauen statt sie ins Leere laufen zu lassen."""
    try:
        import ortools.sat.python.cp_model  # noqa: F401
    except ImportError:
        return False
    return True


def _grid_estimate(request: PatternRequest) -> int:
    cell_l, cell_w = request.cell_length_mm, request.cell_width_mm
    if cell_l <= 0 or cell_w <= 0:
        return 0
    length = request.usable_length_mm
    width = request.usable_width_mm
    upright = int(length // cell_l) * int(width // cell_w)
    crosswise = int(length // cell_w) * int(width // cell_l)
    return max(upright, crosswise)


def solve_max_count(request: PatternRequest) -> PatternLayout | None:
    """Dichteste Anordnung per CP-SAT. None, wenn nicht anwendbar.

    Modelliert wird ueber optionale Intervalle mit variabler Ausdehnung: jeder
    Kandidatenkoerper kann gesetzt oder weggelassen und dabei gedreht oder nicht
    gedreht werden. AddNoOverlap2D verbietet Ueberschneidungen, die Zielfunktion
    maximiert die Zahl der gesetzten Koerper.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    estimate = _grid_estimate(request)
    if estimate <= 0 or estimate > LARGE_INSTANCE_THRESHOLD:
        return None

    # Millimeter auf ganze Zehntel runden: CP-SAT rechnet ganzzahlig, und
    # Zehntelmillimeter sind feiner als jede Palettierung je braucht.
    scale = 10
    item_l = round((request.item_length_mm + request.gap_mm) * scale)
    item_w = round((request.item_width_mm + request.gap_mm) * scale)
    bounds_l = round(request.usable_length_mm * scale)
    bounds_w = round(request.usable_width_mm * scale)
    if item_l <= 0 or item_w <= 0 or bounds_l <= 0 or bounds_w <= 0:
        return None

    upper = min(estimate + 4, LARGE_INSTANCE_THRESHOLD + 4)
    model = cp_model.CpModel()
    placed, rotations, xs, ys = [], [], [], []
    x_intervals, y_intervals = [], []

    for i in range(upper):
        present = model.NewBoolVar("p" + str(i))
        rotated = model.NewBoolVar("r" + str(i))
        size_x = model.NewIntVar(min(item_l, item_w), max(item_l, item_w), "sx" + str(i))
        size_y = model.NewIntVar(min(item_l, item_w), max(item_l, item_w), "sy" + str(i))
        model.Add(size_x == item_l).OnlyEnforceIf(rotated.Not())
        model.Add(size_x == item_w).OnlyEnforceIf(rotated)
        model.Add(size_y == item_w).OnlyEnforceIf(rotated.Not())
        model.Add(size_y == item_l).OnlyEnforceIf(rotated)

        x = model.NewIntVar(0, bounds_l, "x" + str(i))
        y = model.NewIntVar(0, bounds_w, "y" + str(i))
        end_x = model.NewIntVar(0, bounds_l, "ex" + str(i))
        end_y = model.NewIntVar(0, bounds_w, "ey" + str(i))
        model.Add(end_x == x + size_x)
        model.Add(end_y == y + size_y)

        x_intervals.append(model.NewOptionalIntervalVar(x, size_x, end_x, present, "xi" + str(i)))
        y_intervals.append(model.NewOptionalIntervalVar(y, size_y, end_y, present, "yi" + str(i)))
        placed.append(present)
        rotations.append(rotated)
        xs.append(x)
        ys.append(y)

    # Symmetriebrechung: die gesetzten Koerper muessen die vorderen Plaetze
    # belegen. Ohne das sucht der Loeser durch viele gleichwertige Permutationen
    # derselben Anordnung.
    for i in range(upper - 1):
        model.AddImplication(placed[i + 1], placed[i])

    model.AddNoOverlap2D(x_intervals, y_intervals)
    model.Maximize(sum(placed))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_deterministic_time = DETERMINISTIC_LIMIT
    solver.parameters.random_seed = 0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.info("CP-SAT ohne Ergebnis (Status %s)", solver.StatusName(status))
        return None

    footprints: list[Footprint] = []
    for i in range(upper):
        if not solver.Value(placed[i]):
            continue
        rotated = bool(solver.Value(rotations[i]))
        length = request.item_width_mm if rotated else request.item_length_mm
        width = request.item_length_mm if rotated else request.item_width_mm
        footprints.append(
            Footprint(solver.Value(xs[i]) / scale, solver.Value(ys[i]) / scale, length, width, rotated)
        )

    if not footprints:
        return None

    note = ("Dichteste Lage per CP-SAT ermittelt (ein Suchfaden, deterministisches Zeitbudget).",)
    return center_in_bounds(PatternLayout(sort_footprints(footprints), note), request)
