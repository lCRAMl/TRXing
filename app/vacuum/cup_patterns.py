"""Muster, nach denen die Sauger auf der Platte sitzen.

Getrennt von SuctionLayoutEngine, damit ein neues Muster eine Funktion und
einen Registryeintrag braucht - und keinen Eingriff in die Verteillogik oder
den Tab. Dieselbe Bauweise wie bei den Palettiermustern.

Jede Strategie bekommt ein Rechteck (die nutzbare Plattenflaeche, Randabstand
schon abgezogen), das Rastermass und gibt Mittelpunkte zurueck. Ob die Sauger
anschliessend ausgeduennt werden, weil weniger gewuenscht sind, entscheidet der
Aufrufer.

Zur dichtesten Packung: das versetzte Raster ist der Grund, warum es diese
Auswahl ueberhaupt gibt. Kreise gleicher Groesse lassen sich im Quadratraster
nur bis zu einem Flaechenanteil von pi/4 = 78,5 Prozent packen, versetzt
dagegen bis pi/(2*sqrt(3)) = 90,7 Prozent. Auf derselben Platte passen damit
rund fuenfzehn Prozent mehr Sauger - und weil jeder Sauger dieselbe wirksame
Flaeche hat, ist das unmittelbar mehr Auflage- und Wirkflaeche.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ArrangementRequest:
    """Eingabe eines Saugermusters.

    Die Spanne ist der Bereich, in dem Saugermittelpunkte liegen duerfen - der
    Randabstand und der halbe Aussendurchmesser sind bereits abgezogen.
    """

    span_x_mm: float
    span_y_mm: float

    #: Kleinster zulaessiger Mittenabstand zweier Sauger.
    pitch_mm: float

    #: Rechtecke der Pakete unter der Platte, im Koordinatensystem der Platte.
    #: Nur das Muster "ueber den Paketen" wertet sie aus.
    package_rects: tuple[tuple[float, float, float, float], ...] = ()

    #: Versatz der Spanne gegenueber dem Plattenursprung.
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0


@dataclass(frozen=True, slots=True)
class Arrangement:
    """Ergebnis eines Saugermusters."""

    #: Mittelpunkte, absolut im Koordinatensystem der Platte.
    centers: tuple[tuple[float, float], ...] = ()
    columns: int = 0
    rows: int = 0
    pitch_x_mm: float = 0.0
    pitch_y_mm: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.centers)


StrategyFunction = Callable[[ArrangementRequest], Arrangement]

_REGISTRY: dict[str, StrategyFunction] = {}
_LABELS: dict[str, str] = {}
_DESCRIPTIONS: dict[str, str] = {}


def register(strategy_id: str, label: str, description: str):
    """Dekorator zur Anmeldung eines Saugermusters."""

    def decorator(function: StrategyFunction) -> StrategyFunction:
        if strategy_id in _REGISTRY:
            raise ValueError("Saugermuster '" + strategy_id + "' ist bereits angemeldet")
        _REGISTRY[strategy_id] = function
        _LABELS[strategy_id] = label
        _DESCRIPTIONS[strategy_id] = description
        return function

    return decorator


def available() -> tuple[str, ...]:
    """Alle angemeldeten Muster in Anzeigereihenfolge."""
    return tuple(_REGISTRY)


def label_of(strategy_id: str) -> str:
    return _LABELS.get(strategy_id, strategy_id)


def description_of(strategy_id: str) -> str:
    return _DESCRIPTIONS.get(strategy_id, "")


def generate(strategy_id: str, request: ArrangementRequest) -> Arrangement:
    strategy = _REGISTRY.get(strategy_id)
    if strategy is None:
        raise KeyError(
            "Unbekanntes Saugermuster '" + strategy_id + "'. Bekannt sind: "
            + ", ".join(available())
        )
    return strategy(request)


def _grid_counts(request: ArrangementRequest) -> tuple[int, int]:
    """Spalten und Reihen eines Quadratrasters am Mindestabstand."""
    if request.pitch_mm <= 0.0:
        return 0, 0
    columns = int(request.span_x_mm // request.pitch_mm) + 1
    rows = int(request.span_y_mm // request.pitch_mm) + 1
    return max(0, columns), max(0, rows)


def _spread(span_mm: float, count: int, origin_mm: float, centre_mm: float) -> list[float]:
    """Positionen einer Achse: gleichmaessig ueber die Spanne verteilt.

    Bei einer einzigen Position sitzt sie in der Mitte - sonst klebte sie am
    Rand, und die Platte kippte beim Anheben.
    """
    if count <= 0:
        return []
    if count == 1:
        return [centre_mm]
    step = span_mm / (count - 1)
    return [origin_mm + i * step for i in range(count)]


# Raster ------------------------------------------------------------------------

@register(
    "grid_spread",
    "Raster, gleichmaessig verteilt",
    "Quadratraster ueber die ganze Platte gespreizt. Der Regelfall: die Sauger "
    "sitzen so weit auseinander wie moeglich und greifen damit die Kartonflaeche "
    "breit ab.",
)
def grid_spread(request: ArrangementRequest) -> Arrangement:
    columns, rows = _grid_counts(request)
    xs = _spread(request.span_x_mm, columns, request.origin_x_mm,
                 request.origin_x_mm + request.span_x_mm / 2.0)
    ys = _spread(request.span_y_mm, rows, request.origin_y_mm,
                 request.origin_y_mm + request.span_y_mm / 2.0)
    centers = tuple((x, y) for y in ys for x in xs)
    return Arrangement(
        centers=centers,
        columns=columns,
        rows=rows,
        pitch_x_mm=(request.span_x_mm / (columns - 1)) if columns > 1 else 0.0,
        pitch_y_mm=(request.span_y_mm / (rows - 1)) if rows > 1 else 0.0,
    )


@register(
    "grid_dense",
    "Raster, dicht an dicht",
    "Quadratraster am Mindestabstand, mittig auf der Platte. Gleiche Anzahl wie "
    "das gespreizte Raster, aber auf kleinerer Flaeche zusammengezogen - fuer "
    "Pakete, die deutlich kleiner sind als die Platte.",
)
def grid_dense(request: ArrangementRequest) -> Arrangement:
    columns, rows = _grid_counts(request)
    pitch = request.pitch_mm
    used_x = (columns - 1) * pitch
    used_y = (rows - 1) * pitch
    start_x = request.origin_x_mm + (request.span_x_mm - used_x) / 2.0
    start_y = request.origin_y_mm + (request.span_y_mm - used_y) / 2.0
    centers = tuple(
        (start_x + c * pitch, start_y + r * pitch)
        for r in range(rows)
        for c in range(columns)
    )
    return Arrangement(centers=centers, columns=columns, rows=rows,
                       pitch_x_mm=pitch, pitch_y_mm=pitch)


@register(
    "hexagonal",
    "Dichteste Packung (maximale Anzahl)",
    "Versetzte Reihen im gleichseitigen Dreieck. Die dichteste Anordnung "
    "gleich grosser Kreise ueberhaupt: rund 15 Prozent mehr Sauger als im "
    "Quadratraster und damit die groesste erreichbare Auflage- und Wirkflaeche.",
)
def hexagonal(request: ArrangementRequest) -> Arrangement:
    """Versetztes Raster - die dichteste Packung gleich grosser Kreise.

    Die Reihen ruecken auf das sqrt(3)/2-fache des Rastermasses zusammen, weil
    jeder Sauger in die Luecke zwischen zwei Saugern der Reihe darunter faellt.
    Der Mittenabstand zu allen sechs Nachbarn bleibt dabei genau das
    Rastermass - der geforderte Mindestabstand ist also eingehalten.

    Jede zweite Reihe ist um ein halbes Rastermass versetzt und verliert dadurch
    am rechten Rand unter Umstaenden einen Platz. Der Gewinn aus den engeren
    Reihen ueberwiegt das deutlich.
    """
    pitch = request.pitch_mm
    if pitch <= 0.0:
        return Arrangement()

    row_pitch = pitch * math.sqrt(3.0) / 2.0
    rows = int(request.span_y_mm // row_pitch) + 1
    full_columns = int(request.span_x_mm // pitch) + 1
    if rows <= 0 or full_columns <= 0:
        return Arrangement()

    # Versetzte Reihen um ein halbes Rastermass einruecken; passt der letzte
    # Sauger dadurch nicht mehr, faellt er weg.
    offset_columns = full_columns
    if (offset_columns - 1) * pitch + pitch / 2.0 > request.span_x_mm + 1e-9:
        offset_columns -= 1

    used_y = (rows - 1) * row_pitch
    start_y = request.origin_y_mm + (request.span_y_mm - used_y) / 2.0

    # Der gesamte Block wird EINMAL zentriert, nicht jede Reihe fuer sich.
    #
    # Reihenweise zu zentrieren liegt nahe, zerstoert aber genau das, was die
    # dichteste Packung ausmacht: der waagerechte Versatz zwischen zwei Reihen
    # ist dann nicht mehr ein halbes Rastermass, sondern das, was die
    # Zentrierung zufaellig ergibt. Der Abstand zur Nachbarreihe faellt damit
    # unter das Rastermass - gemessen 39,7 statt 44 mm, die Sauger wuerden sich
    # ueberlappen. Mit gemeinsamem Ursprung bleibt es ein echtes Dreiecksgitter,
    # in dem der Abstand zu allen sechs Nachbarn exakt das Rastermass ist.
    block_width = max(
        (full_columns - 1) * pitch,
        (offset_columns - 1) * pitch + pitch / 2.0 if offset_columns > 0 else 0.0,
    )
    start_x = request.origin_x_mm + (request.span_x_mm - block_width) / 2.0

    centers: list[tuple[float, float]] = []
    for row in range(rows):
        staggered = row % 2 == 1
        columns = offset_columns if staggered else full_columns
        if columns <= 0:
            continue
        shift = pitch / 2.0 if staggered else 0.0
        for column in range(columns):
            centers.append((start_x + shift + column * pitch, start_y + row * row_pitch))

    note = (
        "Versetzte Reihen: der Reihenabstand betraegt das " + format(math.sqrt(3.0) / 2.0, ".3f")
        + "-fache des Rastermasses. Der Mittenabstand zu allen Nachbarn bleibt "
        "dabei das volle Rastermass.",
    )
    return Arrangement(
        centers=tuple(centers), columns=full_columns, rows=rows,
        pitch_x_mm=pitch, pitch_y_mm=row_pitch, notes=note,
    )


@register(
    "perimeter",
    "Nur am Rand",
    "Sauger ausschliesslich auf dem aeusseren Ring des Rasters, die Mitte "
    "bleibt frei. Fuer grossflaechige, steife Werkstuecke, bei denen der Halt "
    "am Rand entsteht und die Mitte nur Leitungen kostet.",
)
def perimeter(request: ArrangementRequest) -> Arrangement:
    columns, rows = _grid_counts(request)
    xs = _spread(request.span_x_mm, columns, request.origin_x_mm,
                 request.origin_x_mm + request.span_x_mm / 2.0)
    ys = _spread(request.span_y_mm, rows, request.origin_y_mm,
                 request.origin_y_mm + request.span_y_mm / 2.0)

    centers = tuple(
        (x, y)
        for row, y in enumerate(ys)
        for column, x in enumerate(xs)
        if row in (0, rows - 1) or column in (0, columns - 1)
    )
    notes = ()
    if rows <= 2 or columns <= 2:
        notes = ("Raster zu klein fuer eine freie Mitte - die Platte ist voll bestueckt.",)
    return Arrangement(centers=centers, columns=columns, rows=rows, notes=notes)


@register(
    "over_packages",
    "Nur ueber den Paketen",
    "Dichteste Packung, aber nur dort, wo tatsaechlich ein Paket liegt. "
    "Unbelegte Positionen entfallen ganz - sie koennten sonst keine Fremdluft "
    "ziehen und auch keine Leitung belegen.",
)
def over_packages(request: ArrangementRequest) -> Arrangement:
    """Dichteste Packung, auf die Paketflaechen beschraenkt.

    Der praktische Nutzen liegt in der Stroemungsbilanz. Ein offener Sauger
    zieht bei -0,6 bar ungedrosselt mehrere Kubikmeter Luft je Stunde; eine
    Platte, die zur Haelfte ins Leere saugt, bricht im Vakuum zusammen. Wer die
    Platte fuer ein bekanntes Produkt baut, setzt gar nicht erst Sauger dorthin,
    wo nie ein Karton liegt.

    Massgeblich ist - wie bei der Kontaktpruefung - der Dichtlippenring: gesetzt
    wird nur, wo er vollstaendig auf einer Kartonflaeche liegen wuerde. Ein
    Sauger halb ueber der Kante traegt nicht und bringt nichts.
    """
    base = hexagonal(request)
    if not request.package_rects:
        return Arrangement(
            centers=base.centers, columns=base.columns, rows=base.rows,
            pitch_x_mm=base.pitch_x_mm, pitch_y_mm=base.pitch_y_mm,
            notes=("Keine Paketflaechen bekannt - die Platte ist dichtest bestueckt.",),
        )

    # Der Dichtlippenradius steckt im Rastermass: pitch = Aussendurchmesser +
    # Mindestabstand. Fuer die Pruefung genuegt der halbe Aussendurchmesser als
    # sichere obere Schranke des Dichtlippenradius.
    radius = request.pitch_mm / 2.0
    kept = tuple(
        (x, y)
        for x, y in base.centers
        if any(
            rect[0] <= x - radius and x + radius <= rect[0] + rect[2]
            and rect[1] <= y - radius and y + radius <= rect[1] + rect[3]
            for rect in request.package_rects
        )
    )
    notes = base.notes + (
        "Von " + str(base.count) + " moeglichen Positionen sind " + str(len(kept))
        + " besetzt - die uebrigen laegen nicht vollstaendig auf einem Paket.",
    )
    if not kept:
        notes = notes + (
            "Kein Sauger liegt vollstaendig auf einem Paket. Plattengroesse, "
            "Saugergroesse oder Paketanordnung pruefen.",
        )
    return Arrangement(
        centers=kept, columns=base.columns, rows=base.rows,
        pitch_x_mm=base.pitch_x_mm, pitch_y_mm=base.pitch_y_mm, notes=notes,
    )
