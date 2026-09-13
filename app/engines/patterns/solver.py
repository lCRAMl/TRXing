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

from __future__ import annotations

import logging

from app.dto.common import Footprint
from app.engines.patterns.base import PatternLayout, PatternRequest, center_in_bounds, sort_footprints

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
