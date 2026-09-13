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

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.dto.common import Footprint


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
