"""Der Vakuumrechner.

Ablauf, der auch den Trace gliedert (Spezifikation 41):

    Plattengeometrie
      -> Paketanordnung
      -> Saugerpositionen
      -> Ueberdeckung je Sauger
      -> wirksame und offene Sauger
      -> wirksame Flaeche
      -> Leckage durch den Karton
      -> Fremdluft der offenen Sauger
      -> Arbeitspunkt
      -> verfuegbare Haltekraft
      -> maximale Hebemasse

Der wesentliche Unterschied zur naheliegenden Rechnung steckt im Arbeitspunkt.
Naheliegend waere: Sollvakuum annehmen, Kraft daraus rechnen, benoetigten
Volumenstrom danebenstellen und warnen, wenn er die Leistung uebersteigt. Das
liefert aber ein Ergebnis, das als sicher ausgewiesen wird, obwohl es nie
eintritt - denn wenn der Erzeuger den Strom nicht schafft, stellt sich das
Sollvakuum eben nicht ein.

Gerechnet wird deshalb der Schnittpunkt zweier Kurven:

    Bedarf      steigt mit dem Unterdruck (mehr Druckdifferenz, mehr Fremdluft)
    Angebot     faellt mit dem Unterdruck (Kennlinie des Erzeugers)

Der Schnittpunkt ist das tatsaechlich erreichbare Vakuum; daraus folgt die
Haltekraft. Ein offener Sauger senkt damit unmittelbar die Traglast, statt nur
eine Warnung zu erzeugen. Ueber VacuumInput.solve_operating_point laesst sich
die einfache Betrachtung einschalten; beide Zahlen stehen im Ergebnis.

Gesucht wird per Bisektion: Angebot minus Bedarf ist bei null Unterdruck positiv
und beim Endvakuum negativ, dazwischen monoton genug fuer eine sichere
Einschachtelung. Fuenfzig Schritte genuegen fuer eine Genauigkeit weit unterhalb
jeder Messbarkeit.
"""

from __future__ import annotations

import time

from app.core.cancellation import CancellationToken, never
from app.core.result import Status, classify
from app.core.trace import CalculationTrace, new_trace
from app.core.units import m3s_to_m3h, pa_to_mbar
from app.dto.common import CalculationMeta
from app.dto.suction import RestrictorMode
from app.dto.vacuum import (
    FlowBreakdown,
    ForceBreakdown,
    GripDirection,
    LeakageModel,
    VacuumInput,
    VacuumResult,
)
from app.engines.vacuum import arrangements, contact, flow, force, layout
from app.engines.vacuum.contact import ContactSummary
from app.engines.vacuum.force import ForceResult

ALGORITHM_VERSION = "1.0"
MODULE_ID = "vacuum"

#: Schritte der Bisektion fuer den Arbeitspunkt.
SOLVER_ITERATIONS = 50

#: Bis zu dieser Abweichung gelten Faltendurchmesser und Datenblattkraft als
#: uebereinstimmend - dann gibt es nichts zu vermerken.
D2_AGREEMENT_PCT = 1.0

#: Oberhalb dieser Abweichung ist d2 erkennbar nicht die kraftuebertragende
#: Flaeche der Bauform, sondern ein anderes Konstruktionsmass. Das ist eine
#: andere Aussage als "weicht etwas ab" und wird deshalb anders formuliert.
D2_MISMATCH_PCT = 25.0


class VacuumError(Exception):
    """Die Aufgabe ist so nicht loesbar - ein normales Ergebnis, kein
    Programmfehler. Beispiel: die Platte ist kleiner als ein Sauger."""


class VacuumCalculator:
    """Rechnet eine Saugerplatte durch."""

    def __init__(self) -> None:
        self._layout_engine = layout.SuctionLayoutEngine()

    def calculate(
        self,
        request: VacuumInput,
        token: CancellationToken | None = None,
        request_id: int = 0,
        state_revision: int = 0,
    ) -> VacuumResult:
        token = token or never()
        started = time.perf_counter()
        trace = new_trace(MODULE_ID, ALGORITHM_VERSION, request_id)
        warnings: list[str] = []

        self._record_assumptions(request, trace)

        trace.step(
            "plattengeometrie",
            format(request.plate.length_mm, ".0f") + " x " + format(request.plate.width_mm, ".0f")
            + " mm, Sauger " + request.cup.name,
        )

        # Zuerst die Pakete, dann die Sauger. Die Reihenfolge ist nicht
        # beliebig: das Saugermuster "nur ueber den Paketen" braucht die
        # Kartonflaechen, um zu entscheiden, wo ueberhaupt ein Sauger sinnvoll
        # ist. Umgekehrt braucht die Paketanordnung nichts von den Saugern.
        packages, package_notes = layout.package_layout(
            request.package, request.plate, request.package_count,
            strategy=request.pattern_id or "uniform_grid",
        )
        warnings.extend(package_notes)
        if not packages:
            raise VacuumError(
                package_notes[0] if package_notes
                else "Es laesst sich kein Paket anordnen."
            )
        package_rects = tuple(
            (f.x_mm, f.y_mm, f.length_mm, f.width_mm) for f in packages
        )
        trace.step(
            "paketanordnung",
            str(len(packages)) + " Paket(e), Muster " + (request.pattern_id or "uniform_grid"),
        )
        token.raise_if_cancelled()

        suction = self._layout_engine.distribute(
            request.cup, request.plate, request.requested_cup_count,
            arrangement_id=request.arrangement_id, package_rects=package_rects,
        )
        if not suction.placements:
            raise VacuumError(
                suction.notes[0] if suction.notes
                else "Auf der Platte laesst sich kein Sauger unterbringen."
            )
        warnings.extend(suction.notes)
        trace.step(
            "saugerpositionen",
            arrangements.label_of(request.arrangement_id) + ": " + str(suction.count)
            + " von maximal " + str(suction.max_count),
            pitch_x=round(suction.pitch_x_mm, 1),
            pitch_y=round(suction.pitch_y_mm, 1),
        )
        token.raise_if_cancelled()

        summary = contact.classify(
            suction.placements, packages, request.cup, request.count_partial_as_sealed
        )
        trace.step(
            "ueberdeckung",
            str(summary.sealed_count) + " wirksam, " + str(summary.partial_count) + " teilweise, "
            + str(summary.open_count) + " offen",
        )
        trace.step("wirksame_flaeche", format(summary.effective_area_mm2 / 100.0, ".1f") + " cm2")
        token.raise_if_cancelled()

        bearing = contact.bearing_count(summary, request.count_partial_as_sealed)
        leaking = summary.open_count + (0 if request.count_partial_as_sealed else summary.partial_count)

        achieved_pa, breakdown = self._solve_operating_point(request, summary, bearing, leaking, trace)
        token.raise_if_cancelled()

        forces = force.evaluate(
            cup=request.cup,
            sealed_count=bearing,
            vacuum_pa=achieved_pa,
            mass_kg=request.package.weight_kg * len(packages),
            safety_factor=request.safety_factor,
            acceleration_ms2=request.acceleration_ms2,
            gravity_ms2=request.gravity_ms2,
            grip=request.grip,
            friction_factor=request.friction_factor,
        )
        trace.step(
            "haltekraft",
            format(forces.total_holding_n, ".1f") + " N aus " + str(bearing) + " Saugern zu "
            + format(forces.per_cup_n, ".2f") + " N",
        )
        trace.step("maximale_masse", format(forces.max_mass_kg, ".2f") + " kg")

        warnings.extend(self._warnings(request, summary, breakdown, forces, achieved_pa, bearing))

        actual_mass = request.package.weight_kg * len(packages)
        status = (
            classify(forces.max_mass_kg, actual_mass)
            if actual_mass > 0
            else (Status.SAFE if forces.max_mass_kg > 0 else Status.INSUFFICIENT)
        )

        required_cups = force.required_cup_count(
            actual_mass, request.cup, achieved_pa, request.safety_factor,
            request.acceleration_ms2, request.gravity_ms2, request.grip, request.friction_factor,
        )

        meta = CalculationMeta(
            module_id=MODULE_ID,
            algorithm_version=ALGORITHM_VERSION,
            request_id=request_id,
            state_revision=state_revision,
            calculation_id=trace.calculation_id,
            duration_s=time.perf_counter() - started,
        )

        return VacuumResult(
            meta=meta,
            plate=request.plate,
            cup=request.cup,
            placements=suction.placements,
            contacts=summary.contacts,
            package_rects=package_rects,
            arrangement_id=request.arrangement_id,
            pitch_x_mm=suction.pitch_x_mm,
            pitch_y_mm=suction.pitch_y_mm,
            total_cup_count=suction.count,
            sealed_count=summary.sealed_count,
            partial_count=summary.partial_count,
            open_count=summary.open_count,
            max_cup_count=suction.max_count,
            effective_area_mm2=summary.effective_area_mm2,
            target_vacuum_pa=request.target_vacuum_pa,
            achieved_vacuum_pa=achieved_pa,
            flow=breakdown,
            force=ForceBreakdown(
                theoretical_per_cup_n=forces.per_cup_n,
                total_holding_n=forces.total_holding_n,
                required_n=forces.required_n,
                cup_limit_n=forces.cup_limit_n,
                limited_by_cup_strength=forces.limited_by_cup_strength,
            ),
            max_package_mass_kg=forces.max_mass_kg,
            actual_mass_kg=actual_mass,
            required_cup_count=required_cups,
            status=status,
            warnings=tuple(warnings),
            trace=trace.freeze(),
        )

    # Arbeitspunkt -------------------------------------------------------------

    def _demand_m3s(self, request: VacuumInput, summary: ContactSummary, bearing: int,
                    leaking: int, vacuum_pa: float) -> tuple[float, float, float]:
        """Volumenstrombedarf beim gegebenen Unterdruck.

        Zurueck kommen (offene Sauger, Karton, Summe) - getrennt, weil
        Spezifikation 21 genau diese Aufteilung anzeigen will.
        """
        per_open = flow.open_cup_flow_m3s(
            request.cup, request.restrictor, vacuum_pa, request.ambient_pa
        )
        open_flow = per_open * max(0, leaking)

        from app.engines.vacuum.leakage import workpiece_flow_m3s

        workpiece = workpiece_flow_m3s(request.leakage, vacuum_pa, summary.effective_area_mm2, bearing)
        return open_flow, workpiece, open_flow + workpiece

    def _breakdown_at(
        self, request: VacuumInput, summary: ContactSummary, bearing: int, leaking: int,
        vacuum_pa: float,
    ) -> FlowBreakdown:
        """Vollstaendige Strombilanz bei einem bestimmten Unterdruck.

        Offene und teilweise aufliegende Sauger werden getrennt ausgewiesen,
        obwohl sie physikalisch gleich lecken - Spezifikation 21 verlangt die
        Aufschluesselung, und dem Benutzer sagt sie, an welcher Stelle er
        ansetzen muss.
        """
        per_open = flow.open_cup_flow_m3s(request.cup, request.restrictor, vacuum_pa, request.ambient_pa)
        leaking_partial = 0 if request.count_partial_as_sealed else summary.partial_count
        _, workpiece, total = self._demand_m3s(request, summary, bearing, leaking, vacuum_pa)
        return FlowBreakdown(
            open_cups_m3s=per_open * summary.open_count,
            partial_cups_m3s=per_open * leaking_partial,
            workpiece_m3s=workpiece,
            total_required_m3s=total,
            available_m3s=flow.pump_flow_m3s(request.pump, vacuum_pa),
        )

    def _solve_operating_point(
        self, request: VacuumInput, summary: ContactSummary, bearing: int, leaking: int,
        trace: CalculationTrace,
    ) -> tuple[float, FlowBreakdown]:
        """Erreichbares Vakuum und die zugehoerige Strombilanz."""
        ceiling = min(request.target_vacuum_pa, request.pump.max_vacuum_pa)
        if ceiling <= 0.0:
            ceiling = request.target_vacuum_pa

        at_target = self._breakdown_at(request, summary, bearing, leaking, ceiling)

        if not request.solve_operating_point or at_target.total_required_m3s <= at_target.available_m3s:
            # Der Erzeuger schafft den Bedarf beim Sollwert - das Sollvakuum
            # stellt sich ein, und der Arbeitspunkt ist genau dieser Punkt.
            trace.step(
                "arbeitspunkt",
                ("Sollvakuum erreicht" if request.solve_operating_point else "Sollvakuum vorgegeben")
                + ": " + format(pa_to_mbar(ceiling), ".0f") + " mbar",
                bedarf_m3h=round(m3s_to_m3h(at_target.total_required_m3s), 2),
                angebot_m3h=round(m3s_to_m3h(at_target.available_m3s), 2),
            )
            return ceiling, at_target

        # Bisektion: Angebot minus Bedarf ist bei null Unterdruck positiv (kein
        # Druckgefaelle, also keine Leckage) und beim Sollwert negativ. Der
        # Nulldurchgang dazwischen ist der Arbeitspunkt.
        low, high = 0.0, ceiling
        for _ in range(SOLVER_ITERATIONS):
            middle = (low + high) / 2.0
            _, _, demand = self._demand_m3s(request, summary, bearing, leaking, middle)
            if flow.pump_flow_m3s(request.pump, middle) >= demand:
                low = middle
            else:
                high = middle

        achieved = low
        breakdown = self._breakdown_at(request, summary, bearing, leaking, achieved)
        trace.step(
            "arbeitspunkt",
            "Sollvakuum nicht erreichbar - Schnittpunkt bei "
            + format(pa_to_mbar(achieved), ".0f") + " mbar statt "
            + format(pa_to_mbar(ceiling), ".0f") + " mbar",
            bedarf_m3h=round(m3s_to_m3h(breakdown.total_required_m3s), 2),
            angebot_m3h=round(m3s_to_m3h(breakdown.available_m3s), 2),
        )
        return achieved, breakdown

    # Annahmen und Warnungen ---------------------------------------------------

    def _record_assumptions(self, request: VacuumInput, trace: CalculationTrace) -> None:
        """Spezifikation 25: jede nicht belegte Groesse wird benannt."""
        cup = request.cup
        trace.assumption(
            "saugerkraft",
            "Wirksame Flaeche aus der Datenblattkraft bei -0,6 bar zurueckgerechnet. "
            "Bei diesem Unterdruck entspricht das Ergebnis exakt dem Herstellerwert.",
            source="datasheet",
            value=round(force.datasheet_effective_area_mm2(cup), 1),
        )
        deviation = cup.force_area_deviation_pct
        if abs(deviation) > D2_AGREEMENT_PCT:
            if abs(deviation) > D2_MISMATCH_PCT:
                # Bei manchen Baureihen ist der Faltendurchmesser konstruktiv
                # gar nicht die kraftuebertragende Flaeche - bei Schmalz SPB2f
                # in den Groessen 30 bis 50 liegt er um bis zu 81 Prozent
                # daneben. Das als blosse "Abweichung" zu melden waere
                # irrefuehrend: es sieht nach einem Fehler in der Rechnung aus,
                # ist aber eine Eigenschaft der Bauform.
                description = (
                    "Bei dieser Baureihe ist der Faltendurchmesser d2 nicht die "
                    "kraftuebertragende Flaeche (Abweichung " + format(deviation, "+.0f")
                    + " Prozent). Gerechnet wird ausschliesslich mit der Datenblattkraft; "
                    "d2 dient nur als Gegenprobe und geht in kein Ergebnis ein."
                )
            else:
                description = (
                    "Die Kreisflaeche des inneren Faltendurchmessers d2 weicht um "
                    + format(deviation, "+.1f") + " Prozent von der Datenblattkraft ab. "
                    "Gerechnet wird mit dem Datenblattwert."
                )
            trace.assumption(
                "flaechenabweichung", description, source="datasheet", value=round(deviation, 2)
            )
        trace.assumption(
            "ausflussbeiwert",
            "Ausflussbeiwert " + format(request.restrictor.discharge_coefficient_factor, "g")
            + " fuer die Saugerbohrung. Modellannahme, im Datenblatt nicht enthalten.",
            source="model",
            value=request.restrictor.discharge_coefficient_factor,
        )
        if request.restrictor.mode is RestrictorMode.NONE:
            trace.assumption(
                "ohne_strombegrenzer",
                "Offene Sauger stroemen ungedrosselt durch die volle Bohrung dn = "
                + format(cup.bore_diameter_mm, "g") + " mm.",
                source="config",
            )
        else:
            trace.assumption(
                "strombegrenzer",
                request.restrictor.mode.label + " - Angaben aus der Konfiguration, nicht aus dem Datenblatt.",
                source="config",
            )
        if not request.pump.curve_points:
            trace.assumption(
                "pumpenkennlinie",
                "Ohne Stuetzpunkte wird die Kennlinie als Gerade vom Nennstrom bis zum Endvakuum "
                "angenaehert. Reale Ejektoren knicken frueher ein.",
                source="model",
            )
        if request.leakage.model is not LeakageModel.NONE:
            from app.engines.vacuum.leakage import describe

            trace.assumption(
                "kartonpermeabilitaet",
                describe(request.leakage) + " - Benutzerangabe, keine Materialkonstante.",
                source="config",
                value=request.leakage.permeability_value,
            )
        if request.grip is GripDirection.VERTICAL:
            trace.assumption(
                "reibbeiwert",
                "Reibbeiwert " + format(request.friction_factor, "g")
                + " zwischen Sauger und Karton. Benutzerangabe, in keinem Datenblatt enthalten.",
                source="config",
                value=request.friction_factor,
            )
        if request.acceleration_ms2 > 0.0:
            trace.assumption(
                "beschleunigung",
                "Zusaetzliche Beschleunigung " + format(request.acceleration_ms2, "g")
                + " m/s2 in der Kraftbilanz beruecksichtigt.",
                source="config",
                value=request.acceleration_ms2,
            )

    def _warnings(self, request: VacuumInput, summary: ContactSummary, breakdown: FlowBreakdown,
                  forces: ForceResult, achieved_pa: float, bearing: int) -> list[str]:
        messages: list[str] = []

        if bearing == 0:
            messages.append(
                "Kein Sauger liegt vollstaendig auf einem Paket - die Platte traegt nichts. "
                "Plattengroesse, Saugerraster oder Paketanordnung anpassen."
            )
        if summary.open_count:
            messages.append(
                str(summary.open_count) + " Sauger liegen auf keinem Paket und ziehen Fremdluft ("
                + format(m3s_to_m3h(breakdown.open_cups_m3s), ".1f") + " m3/h)."
            )
        if summary.partial_count and not request.count_partial_as_sealed:
            messages.append(
                str(summary.partial_count) + " Sauger liegen nur teilweise auf. Ihr Dichtlippenring "
                "ist unterbrochen, sie tragen nicht und wirken wie offene Sauger."
            )
        if achieved_pa < request.target_vacuum_pa - 1.0:
            messages.append(
                "Das Sollvakuum von " + format(pa_to_mbar(request.target_vacuum_pa), ".0f")
                + " mbar wird nicht erreicht - der Erzeuger schafft gegen die Leckage nur "
                + format(pa_to_mbar(achieved_pa), ".0f") + " mbar."
            )
        if breakdown.remaining_m3s < 0.0:
            messages.append(
                "Der benoetigte Volumenstrom uebersteigt die verfuegbare Leistung um "
                + format(m3s_to_m3h(-breakdown.remaining_m3s), ".1f") + " m3/h."
            )
        if forces.limited_by_cup_strength:
            messages.append(
                "Nicht das Vakuum begrenzt, sondern der Sauger: die Saugkraft haette "
                + format(achieved_pa * force.datasheet_effective_area_mm2(request.cup) / 1e6, ".1f")
                + " N erreicht, die zulaessige Grenze liegt bei "
                + format(forces.cup_limit_n, ".1f") + " N."
            )
        if request.package.length_mm > 0 and request.cup.min_workpiece_radius_mm > 0:
            half_edge_mm = min(request.package.length_mm, request.package.width_mm) / 2.0
            if half_edge_mm < request.cup.min_workpiece_radius_mm:
                messages.append(
                    "Das Datenblatt nennt fuer " + request.cup.name + " einen Mindestradius von "
                    + format(request.cup.min_workpiece_radius_mm, ".0f")
                    + " mm bei gewoelbten Werkstuecken. Das Paket ist mit "
                    + format(half_edge_mm, ".0f") + " mm halber Kantenlaenge kleiner - bei ebener "
                    "Flaeche unkritisch, bei gewoelbter pruefen."
                )
        return messages
