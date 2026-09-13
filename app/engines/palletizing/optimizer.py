"""Der Palettieroptimierer.

Ablauf, der auch den Trace gliedert (Spezifikation 41):

    Eingabe
      -> erlaubte Ausrichtungen
      -> Musterkandidaten je Ausrichtung
      -> Lagen je Kandidat
      -> Hoehenbegrenzung
      -> Gewichtsbegrenzung Palette
      -> Belastungsgrenze Paket
      -> bester Kandidat

Der Optimierer ist vollstaendig Qt-frei und ohne Dateizugriff. Alles, was er
braucht, kommt als DTO herein; alles, was er liefert, geht als DTO heraus.

Zielsetzung nach Spezifikation 12.3: primaer die Stueckzahl, sekundaer die
Flaechenausnutzung. Bei Gleichstand in beidem gewinnt die Ausrichtung, die
zuerst geprueft wurde - die Reihenfolge ist fest, also ist auch das Ergebnis
reproduzierbar (Spezifikation 39).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.cancellation import CancellationToken, never
from app.core.trace import CalculationTrace, new_trace
from app.dto.common import CalculationMeta, Footprint
from app.dto.package import Orientation, PackageSpec
from app.dto.pallet import (
    LimitingFactor,
    Layer,
    PalletConstraints,
    PalletResult,
    PalletSpec,
    PatternSpec,
    ZMode,
)
from app.engines.palletizing import loads, stacking
from app.engines.patterns import PatternRequest, generate

#: Version des Rechenverfahrens. Steigt, wenn sich Ergebnisse bei gleicher
#: Eingabe aendern - damit ist ein altes Protokoll zuordenbar.
ALGORITHM_VERSION = "1.0"

MODULE_ID = "pallet"

#: Obergrenze der Platzierungen je Lage.
#:
#: Ein Paket von 1 x 1 mm auf einer Europalette ergibt rechnerisch 960000
#: Platzierungen je Lage. Das ist keine Palettierung mehr, sondern eine
#: Verwechslung der Einheit - und es kostet Sekunden, Hunderte Megabyte und
#: eine Darstellung, die sich nicht mehr zeichnen laesst. Zehntausend
#: entspricht einem Raster von 100 x 100 und liegt weit ueber allem, was
#: praktisch vorkommt.
#:
#: Geprueft wird vor dem Erzeugen, nicht danach: eine Abschaetzung aus den
#: Kantenlaengen kostet nichts, das Erzeugen der Platzierungen dagegen alles.
MAX_PLACEMENTS_PER_LAYER = 10_000

#: Obergrenze der Platzierungen im gesamten Stapel.
#:
#: Reiner Sicherheitsriegel gegen Einheitenverwechslungen, keine Leistungsgrenze.
#: Der Rasterindex in loads.py hat die Lastkaskade von quadratisch auf linear
#: gebracht - gemessen: 148800 Platzierungen in 0,9 Sekunden statt 75. Ein
#: knapperer Wert wuerde legitime Faelle abweisen: Kartons von 40 x 30 x 25 mm
#: ergeben auf einer Europalette 52800 Stueck, und das ist eine richtige
#: Antwort auf eine richtige Frage.
#:
#: Die tatsaechliche Grenze liegt in der 3D-Darstellung; sie wird dort
#: behandelt (MAX_RENDERED_BOXES in app/visualization/pallet_3d.py), indem nur
#: die von aussen sichtbaren Pakete gezeichnet werden - nicht dadurch, dass die
#: Berechnung verweigert wird.
MAX_TOTAL_PLACEMENTS = 200_000


class PalletizingError(Exception):
    """Die Aufgabe ist so nicht loesbar - ein normales Ergebnis, kein Fehler
    im Programm. Beispiel: das Paket passt in keiner Ausrichtung auf die
    Palette."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Ein Kandidat: eine Ausrichtung mit ihrer Grundlage."""

    orientation: Orientation
    footprints: tuple[Footprint, ...]
    alternate: tuple[Footprint, ...] | None
    layer_height_mm: float
    notes: tuple[str, ...]

    @property
    def per_layer(self) -> int:
        return len(self.footprints)

    @property
    def used_area_mm2(self) -> float:
        return sum(f.length_mm * f.width_mm for f in self.footprints)


class PalletOptimizer:
    """Ordnet gleiche Pakete auf einer Palette an."""

    def optimize(
        self,
        package: PackageSpec,
        pallet: PalletSpec,
        pattern: PatternSpec,
        constraints: PalletConstraints,
        token: CancellationToken | None = None,
        request_id: int = 0,
        state_revision: int = 0,
    ) -> PalletResult:
        token = token or never()
        started = time.perf_counter()
        trace = new_trace(MODULE_ID, ALGORITHM_VERSION, request_id)
        warnings: list[str] = []

        trace.step(
            "eingabe",
            "Paket " + _dims(package) + " auf " + pallet.id + ", Muster " + pattern.id,
            package_kg=round(package.weight_kg, 3),
        )

        orientations = self._orientations(package, constraints, trace)
        token.raise_if_cancelled()

        candidates = self._candidates(package, pallet, pattern, constraints, orientations, trace, token)
        if not candidates:
            raise PalletizingError(
                "Paket " + _dims(package) + " passt in keiner erlaubten Ausrichtung auf die Palette "
                + format(pallet.usable_length_mm, ".0f") + " x " + format(pallet.usable_width_mm, ".0f") + " mm."
            )

        best = None
        best_key = (-1, -1.0)
        for candidate in candidates:
            token.raise_if_cancelled()
            evaluated = self._evaluate(package, pallet, pattern, constraints, candidate, trace)
            if evaluated is None:
                continue
            layers, limiting, candidate_warnings = evaluated
            total = sum(layer.count for layer in layers)
            used = sum(p.footprint_area_mm2 for p in layers[0].placements) if layers else 0.0
            key = (total, used)
            if key > best_key:
                best_key = key
                best = (candidate, layers, limiting, candidate_warnings)

        if best is None:
            raise PalletizingError(
                "Es passt keine vollstaendige Lage innerhalb der Grenzen: max. Hoehe "
                + format(constraints.max_height_mm, ".0f") + " mm, max. Last "
                + format(constraints.max_load_kg, ".0f") + " kg."
            )

        candidate, layers, limiting, candidate_warnings = best
        warnings.extend(candidate.notes)
        warnings.extend(candidate_warnings)

        trace.step(
            "bester_kandidat",
            candidate.orientation.value + ", " + str(candidate.per_layer) + " je Lage, "
            + str(len(layers)) + " Lagen",
        )

        analysis = loads.analyze(layers, constraints.max_stack_load_kg)
        trace.step(
            "lastverteilung",
            "hoechste Auslastung " + format(analysis.max_load_pct, ".1f") + " %",
            critical=analysis.critical_count,
        )
        if analysis.checked:
            trace.assumption(
                "lastkaskade",
                "Last wird flaechenanteilig nach unten weitergegeben. Brueckenbildung "
                "und Kartonsteifigkeit bleiben unberuecksichtigt.",
                source="model",
            )
        if analysis.critical_count:
            warnings.append(
                str(analysis.critical_count) + " Paket(e) ueberschreiten die zulaessige Stapellast."
            )
        elif analysis.warning_count:
            warnings.append(
                str(analysis.warning_count) + " Paket(e) liegen nahe an der zulaessigen Stapellast."
            )

        return self._build_result(
            package, pallet, pattern, constraints, candidate, layers,
            analysis, limiting, tuple(warnings), trace, started, request_id, state_revision,
        )

    # Teilschritte -------------------------------------------------------------

    def _orientations(
        self, package: PackageSpec, constraints: PalletConstraints, trace: CalculationTrace
    ) -> tuple[Orientation, ...]:
        allowed = package.allowed_orientations() if constraints.allow_tipping or package.allow_tipping else (Orientation.UPRIGHT,)
        trace.step("ausrichtungen", ", ".join(o.value for o in allowed), count=len(allowed))
        return allowed

    def _candidates(
        self,
        package: PackageSpec,
        pallet: PalletSpec,
        pattern: PatternSpec,
        constraints: PalletConstraints,
        orientations: tuple[Orientation, ...],
        trace: CalculationTrace,
        token: CancellationToken,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        options = dict(pattern.options)
        options["use_solver"] = constraints.use_solver

        for orientation in orientations:
            token.raise_if_cancelled()
            length_mm, width_mm, height_mm = package.dimensions_for(orientation)
            self._guard_layer_size(pallet, length_mm, width_mm, constraints.gap_mm)
            request = PatternRequest(
                bounds_length_mm=pallet.usable_length_mm,
                bounds_width_mm=pallet.usable_width_mm,
                item_length_mm=length_mm,
                item_width_mm=width_mm,
                gap_mm=constraints.gap_mm,
                options=options,
            )
            layout = generate(pattern.strategy, request)
            if not layout.footprints:
                continue

            alternate = None
            if pattern.z_mode is ZMode.ROTATE90:
                # Fuer den Wechselverband wird eine zweite Lage mit vertauschten
                # Kanten gebaut. Liefert sie keine gleich grosse Lage, faellt
                # der Stapel auf das Spiegeln zurueck.
                rotated_layout = generate(pattern.strategy, request.rotated())
                if rotated_layout.footprints:
                    alternate = rotated_layout.footprints

            candidates.append(
                _Candidate(
                    orientation=orientation,
                    footprints=layout.footprints,
                    alternate=alternate,
                    layer_height_mm=height_mm,
                    notes=layout.notes,
                )
            )

        trace.step(
            "musterkandidaten",
            pattern.strategy + ": " + ", ".join(
                o.orientation.value + "=" + str(o.per_layer) for o in candidates
            ),
            count=len(candidates),
        )
        return candidates

    @staticmethod
    def _guard_layer_size(pallet: PalletSpec, length_mm: float, width_mm: float, gap_mm: float) -> None:
        """Weist absurd kleine Pakete ab, bevor gerechnet wird.

        Die Abschaetzung ist das naive Raster - sie liegt nie unter der
        tatsaechlichen Stueckzahl, taugt also als obere Schranke.
        """
        cell_l = length_mm + gap_mm
        cell_w = width_mm + gap_mm
        if cell_l <= 0.0 or cell_w <= 0.0:
            return
        estimate = int(pallet.usable_length_mm / cell_l) * int(pallet.usable_width_mm / cell_w)
        if estimate > MAX_PLACEMENTS_PER_LAYER:
            raise PalletizingError(
                "Das Paket " + format(length_mm, ".1f") + " x " + format(width_mm, ".1f")
                + " mm ergaebe rund " + format(estimate, ",d").replace(",", " ")
                + " Pakete je Lage. Die Grenze liegt bei "
                + format(MAX_PLACEMENTS_PER_LAYER, ",d").replace(",", " ")
                + " - bitte die Paketmasse pruefen (Angabe in Millimetern erwartet)."
            )

    def _evaluate(
        self,
        package: PackageSpec,
        pallet: PalletSpec,
        pattern: PatternSpec,
        constraints: PalletConstraints,
        candidate: _Candidate,
        trace: CalculationTrace,
    ) -> tuple[tuple[Layer, ...], LimitingFactor, tuple[str, ...]] | None:
        """Ermittelt die Lagenzahl eines Kandidaten unter allen Grenzen."""
        warnings: list[str] = []
        height = candidate.layer_height_mm
        if height <= 0:
            return None

        by_height = int(constraints.max_height_mm // height) if height > 0 else 0

        layer_weight = candidate.per_layer * package.weight_kg
        by_pallet_load = (
            int(constraints.max_load_kg // layer_weight) if layer_weight > 0 and constraints.max_load_kg > 0 else by_height
        )

        by_stack_load = loads.max_layers_by_stack_load(package.weight_kg, constraints.max_stack_load_kg)
        if by_stack_load <= 0:
            by_stack_load = by_height

        layer_count = max(0, min(by_height, by_pallet_load, by_stack_load))
        if layer_count == 0:
            return None

        if candidate.per_layer * layer_count > MAX_TOTAL_PLACEMENTS:
            raise PalletizingError(
                "Der Stapel ergaebe " + format(candidate.per_layer * layer_count, ",d").replace(",", " ")
                + " Pakete (" + str(candidate.per_layer) + " je Lage in " + str(layer_count)
                + " Lagen). Die Grenze liegt bei "
                + format(MAX_TOTAL_PLACEMENTS, ",d").replace(",", " ")
                + " - bitte die Paketmasse oder die maximale Hoehe pruefen."
            )

        limiting = LimitingFactor.NONE
        if layer_count == by_height and by_height <= by_pallet_load and by_height <= by_stack_load:
            limiting = LimitingFactor.HEIGHT
        if by_pallet_load < by_height and by_pallet_load <= by_stack_load:
            limiting = LimitingFactor.PALLET_LOAD
        if by_stack_load < by_height and by_stack_load < by_pallet_load:
            limiting = LimitingFactor.PACKAGE_LOAD

        layers = stacking.repeat(
            base=candidate.footprints,
            alternate=candidate.alternate,
            layer_count=layer_count,
            z_mode=pattern.z_mode,
            layer_height_mm=height,
            package_weight_kg=package.weight_kg,
            orientation=candidate.orientation,
            bounds_area_mm2=pallet.usable_area_mm2,
            variant=pattern.strategy,
        )

        if pattern.z_mode is ZMode.ROTATE90 and candidate.alternate is None and layer_count > 1:
            warnings.append(
                "Fuer den Wechselverband gibt es keine gleichwertige gedrehte Lage - "
                "die Lagen werden stattdessen gespiegelt."
            )

        # Die Saeulenschranke ist der ungünstigste Fall. Bei einem Verband
        # verteilt sich die Last besser, die tatsaechliche Kaskade kann also
        # mehr Lagen erlauben, als die Schranke zugelassen hat. Umgekehrt kann
        # ein Muster mit freiem Kern einzelne Pakete staerker belasten als die
        # Schranke annimmt - deshalb wird hier nachgeprueft und notfalls
        # gekuerzt, statt der Schranke blind zu vertrauen.
        if constraints.has_stack_load_limit:
            while layer_count > 1:
                analysis = loads.analyze(layers, constraints.max_stack_load_kg)
                if analysis.critical_count == 0:
                    break
                layer_count -= 1
                limiting = LimitingFactor.PACKAGE_LOAD
                layers = stacking.repeat(
                    base=candidate.footprints,
                    alternate=candidate.alternate,
                    layer_count=layer_count,
                    z_mode=pattern.z_mode,
                    layer_height_mm=height,
                    package_weight_kg=package.weight_kg,
                    orientation=candidate.orientation,
                    bounds_area_mm2=pallet.usable_area_mm2,
                    variant=pattern.strategy,
                )

        total = sum(layer.count for layer in layers)
        if constraints.desired_count > 0 and total > constraints.desired_count:
            layers = stacking.trim_to_count(layers, constraints.desired_count)
            limiting = LimitingFactor.DESIRED_COUNT
        elif constraints.desired_count > total:
            warnings.append(
                "Gewuenscht waren " + str(constraints.desired_count) + " Pakete, "
                "innerhalb der Grenzen passen " + str(total) + "."
            )

        return layers, limiting, tuple(warnings)

    def _build_result(
        self,
        package: PackageSpec,
        pallet: PalletSpec,
        pattern: PatternSpec,
        constraints: PalletConstraints,
        candidate: _Candidate,
        layers: tuple[Layer, ...],
        analysis,
        limiting: LimitingFactor,
        warnings: tuple[str, ...],
        trace: CalculationTrace,
        started: float,
        request_id: int,
        state_revision: int,
    ) -> PalletResult:
        total_count = sum(layer.count for layer in layers)
        load_height = len(layers) * candidate.layer_height_mm
        total_height = load_height + (pallet.deck_height_mm if constraints.include_deck_in_height else 0.0)
        total_weight = total_count * package.weight_kg

        base_used = sum(p.footprint_area_mm2 for p in layers[0].placements) if layers else 0.0
        footprint_ratio = base_used / pallet.usable_area_mm2 if pallet.usable_area_mm2 > 0 else 0.0

        package_volume = package.volume_mm3 * total_count
        stack_volume = pallet.usable_area_mm2 * load_height
        volume_ratio = package_volume / stack_volume if stack_volume > 0 else 0.0

        duration = time.perf_counter() - started
        meta = CalculationMeta(
            module_id=MODULE_ID,
            algorithm_version=ALGORITHM_VERSION,
            request_id=request_id,
            state_revision=state_revision,
            calculation_id=trace.calculation_id,
            duration_s=duration,
        )

        return PalletResult(
            meta=meta,
            pallet=pallet,
            package=package,
            pattern_id=pattern.id,
            pattern_name=pattern.name,
            layers=layers,
            total_count=total_count,
            per_layer_count=layers[0].count if layers else 0,
            layer_count=len(layers),
            total_load_height_mm=load_height,
            total_height_mm=total_height,
            total_weight_kg=total_weight,
            used_area_mm2=base_used,
            footprint_utilization_ratio=footprint_ratio,
            volume_utilization_ratio=min(1.0, volume_ratio),
            load=analysis,
            limiting_factor=limiting,
            warnings=warnings,
            trace=trace.freeze(),
        )


def _dims(package: PackageSpec) -> str:
    return (
        format(package.length_mm, ".0f") + "x"
        + format(package.width_mm, ".0f") + "x"
        + format(package.height_mm, ".0f") + " mm"
    )


def build_constraints(
    pallet: PalletSpec,
    package: PackageSpec,
    max_height_mm: float = 0.0,
    max_load_kg: float = 0.0,
    max_stack_load_kg: float = -1.0,
    desired_count: int = 0,
    gap_mm: float = 0.0,
    allow_tipping: bool | None = None,
    use_solver: bool = False,
) -> PalletConstraints:
    """Fuehrt Palettenvorgaben und Benutzereingaben zu einem Regelsatz zusammen.

    Eine Null bedeutet bei Hoehe und Last "nimm den Wert der Palette" - so muss
    die Oberflaeche nicht entscheiden, welcher Wert gewinnt. Bei der Stapellast
    steht -1 fuer "nimm den Wert des Pakets", damit eine ausdrueckliche Null
    (keine Pruefung) davon unterscheidbar bleibt.
    """
    return PalletConstraints(
        max_height_mm=max_height_mm if max_height_mm > 0 else pallet.max_load_height_mm,
        max_load_kg=max_load_kg if max_load_kg > 0 else pallet.max_load_kg,
        max_stack_load_kg=package.max_stack_load_kg if max_stack_load_kg < 0 else max_stack_load_kg,
        desired_count=desired_count,
        gap_mm=gap_mm,
        allow_tipping=package.allow_tipping if allow_tipping is None else allow_tipping,
        use_solver=use_solver,
    )
