"""Verteilung der Sauger auf der Platte und der Pakete unter der Platte.

Zwei getrennte Aufgaben, die haeufig vermischt werden:

SuctionLayoutEngine verteilt Sauger auf der Platte. WELCHES Muster dabei
entsteht, steht in app/engines/vacuum/arrangements.py; hier steht nur, wie aus
Plattengeometrie und Saugergroesse die nutzbare Spanne wird und wie eine
gewuenschte Stueckzahl getroffen wird.

package_layout ordnet die zu hebenden Pakete an. Spezifikation 18 verlangt,
dass dafuer das in der Palettierung gewaehlte Muster verwendbar ist, ohne die
Palettierlogik zu duplizieren - hier passiert genau das.

Die Pakete duerfen ueber die Platte hinausragen. Eine Saugerplatte ist
regelmaessig kleiner als das, was sie hebt: sie greift in die Mitte der Lage,
und die aeusseren Kartons ragen darueber hinaus. Die Plattengroesse begrenzt
deshalb nur, wo Sauger sitzen koennen - nicht, wie die Pakete liegen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median

from app.dto.common import Footprint
from app.dto.package import PackageSpec
from app.dto.suction import SuctionCupSpec, SuctionPlacement
from app.dto.vacuum import VacuumPlateSpec
from app.engines.geometry.shapes import rect_contains_rect
from app.engines.patterns import PatternRequest, generate as generate_pattern
from app.engines.vacuum import arrangements
from app.engines.vacuum.arrangements import Arrangement, ArrangementRequest

#: Obergrenze der Saugerpositionen auf einer Platte.
#:
#: Eine Platte von 2 x 1,5 m mit SPB2 20 ergibt ueber dreitausend Positionen,
#: und jede davon wird anschliessend gegen jedes Paket geprueft. Fuenftausend
#: ist weit mehr, als eine reale Saugerplatte je traegt, und begrenzt zugleich
#: den Aufwand der Ueberdeckungspruefung.
MAX_CUP_POSITIONS = 5000

#: Standardmuster, wenn keines gewaehlt ist.
DEFAULT_ARRANGEMENT = "grid_spread"

#: Toleranz der Frage "liegt dieses Paket noch unter der Platte?".
#:
#: Bewusst groeber als EPSILON_MM der Geometrieschicht: die Paketecken entstehen
#: aus einer Kette von Multiplikationen und Verschiebungen (Zellmass, Zentrierung
#: nach dem Schwerpunkt). Ein Paket, das rechnerisch um ein Zehnmillionstel
#: Millimeter uebersteht, steht in Wahrheit kantenbuendig - mit der schaerferen
#: Toleranz faende die Anzeige dort einen Ueberhang, den niemand messen kann.
PLACEMENT_TOLERANCE_MM = 1e-6

#: Schritte der Suche nach dem Rastermass fuer eine gewuenschte Stueckzahl.
THINNING_ITERATIONS = 40


@dataclass(frozen=True, slots=True)
class SuctionLayout:
    """Ergebnis der Saugerverteilung."""

    placements: tuple[SuctionPlacement, ...] = ()
    arrangement_id: str = DEFAULT_ARRANGEMENT
    columns: int = 0
    rows: int = 0
    max_count: int = 0
    pitch_x_mm: float = 0.0
    pitch_y_mm: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.placements)


class SuctionLayoutEngine:
    """Verteilt Sauger auf einer rechteckigen Platte."""

    def minimum_pitch_mm(self, cup: SuctionCupSpec, plate: VacuumPlateSpec) -> float:
        """Kleinster Mittenabstand zweier Sauger.

        Massgeblich ist das Aussenmass unter Vakuum (Dmax(S) aus dem
        Datenblatt), nicht die Nenngroesse: der Sauger weitet sich beim
        Ansaugen. Dazu der geforderte lichte Mindestabstand.
        """
        return cup.outer_diameter_mm + max(0.0, plate.min_spacing_mm)

    def _base_request(
        self,
        cup: SuctionCupSpec,
        plate: VacuumPlateSpec,
        package_rects: tuple[tuple[float, float, float, float], ...] = (),
    ) -> ArrangementRequest | None:
        """Nutzbare Spanne der Platte. None, wenn kein Sauger daraufpasst."""
        pitch = self.minimum_pitch_mm(cup, plate)
        if pitch <= 0.0:
            return None

        # Der Randabstand gilt von der Plattenkante bis zur aeussersten
        # Saugermitte. Der Sauger selbst braucht dahinter noch seinen halben
        # Aussendurchmesser, sonst haengt er ueber die Kante.
        margin = max(plate.edge_margin_mm, cup.outer_diameter_mm / 2.0)
        span_x = plate.length_mm - 2.0 * margin
        span_y = plate.width_mm - 2.0 * margin
        if span_x < 0.0 or span_y < 0.0:
            return None

        return ArrangementRequest(
            span_x_mm=span_x, span_y_mm=span_y, pitch_mm=pitch,
            package_rects=package_rects, origin_x_mm=margin, origin_y_mm=margin,
        )

    def capacity(
        self,
        cup: SuctionCupSpec,
        plate: VacuumPlateSpec,
        arrangement_id: str = DEFAULT_ARRANGEMENT,
        package_rects: tuple[tuple[float, float, float, float], ...] = (),
    ) -> int:
        """Hoechstzahl der Sauger fuer dieses Muster auf dieser Platte.

        Haengt vom Muster ab: die dichteste Packung nimmt rund fuenfzehn Prozent
        mehr auf als ein Quadratraster, die Randverteilung ein Vielfaches
        weniger. Die Oberflaeche braucht den Wert, um die Obergrenze des
        Eingabefelds zu setzen, bevor gerechnet wird.
        """
        request = self._base_request(cup, plate, package_rects)
        if request is None:
            return 0
        return arrangements.generate(arrangement_id, request).count

    def _thin_to(
        self, arrangement_id: str, request: ArrangementRequest, wanted: int
    ) -> Arrangement:
        """Trifft eine gewuenschte Stueckzahl, ohne das Muster aufzugeben.

        Naheliegend waere, ueberzaehlige Sauger einfach wegzulassen. Das ergibt
        aber eine Platte, die in der unteren Haelfte dicht bestueckt ist und
        oben leer bleibt - sie kippt beim Anheben und greift nur die halbe
        Kartonflaeche ab.

        Stattdessen wird das Rastermass vergroessert, bis das Muster von selbst
        etwa die gewuenschte Zahl liefert. Die Sauger verteilen sich dann wieder
        ueber die ganze Platte, und die Form des Musters bleibt erhalten - ein
        gespreiztes Raster bleibt ein Raster, eine dichteste Packung bleibt
        versetzt.

        Die Stueckzahl faellt monoton mit dem Rastermass, deshalb genuegt eine
        Intervallhalbierung. Der Rest, der danach noch ueber der Vorgabe liegt,
        wird von der obersten Reihe her abgeraeumt.
        """
        low, high = 1.0, 1.0
        # Obergrenze suchen, bei der die Stueckzahl unter die Vorgabe faellt.
        for _ in range(24):
            high *= 1.5
            if arrangements.generate(arrangement_id, replace(request, pitch_mm=request.pitch_mm * high)).count < wanted:
                break

        for _ in range(THINNING_ITERATIONS):
            middle = (low + high) / 2.0
            candidate = arrangements.generate(
                arrangement_id, replace(request, pitch_mm=request.pitch_mm * middle)
            )
            if candidate.count >= wanted:
                low = middle
            else:
                high = middle

        result = arrangements.generate(
            arrangement_id, replace(request, pitch_mm=request.pitch_mm * low)
        )
        if result.count <= wanted:
            return result
        return replace(result, centers=self._drop_surplus(result.centers, result.count - wanted))

    @staticmethod
    def _drop_surplus(
        centers: tuple[tuple[float, float], ...], surplus: int
    ) -> tuple[tuple[float, float], ...]:
        """Entfernt ueberzaehlige Sauger, von der obersten Reihe abwaerts.

        Innerhalb einer Reihe abwechselnd vom rechten und linken Ende, damit die
        verbleibende Bestueckung symmetrisch bleibt und der Schwerpunkt in der
        Mitte. Reicht eine Reihe nicht, wird die naechste darunter angebrochen.

        Die Reihenfolge ist fest, das Ergebnis damit reproduzierbar.
        """
        if surplus <= 0:
            return centers

        by_row: dict[float, list[float]] = {}
        for x, y in centers:
            by_row.setdefault(round(y, 6), []).append(x)

        removed: set[tuple[float, float]] = set()
        for row_y in sorted(by_row, reverse=True):
            if surplus <= 0:
                break
            columns = sorted(by_row[row_y])
            from_right = True
            while surplus > 0 and columns:
                x = columns.pop() if from_right else columns.pop(0)
                removed.add((round(x, 6), row_y))
                from_right = not from_right
                surplus -= 1

        return tuple(
            (x, y) for x, y in centers if (round(x, 6), round(y, 6)) not in removed
        )

    def distribute(
        self,
        cup: SuctionCupSpec,
        plate: VacuumPlateSpec,
        wanted_count: int = 0,
        arrangement_id: str = DEFAULT_ARRANGEMENT,
        package_rects: tuple[tuple[float, float, float, float], ...] = (),
    ) -> SuctionLayout:
        """Verteilt Sauger. wanted_count 0 bedeutet Hoechstbestueckung."""
        request = self._base_request(cup, plate, package_rects)
        if request is None:
            return SuctionLayout(
                arrangement_id=arrangement_id,
                notes=("Die Platte ist fuer diesen Sauger zu klein: benoetigt werden mindestens "
                       + format(cup.outer_diameter_mm + 2.0 * plate.edge_margin_mm, ".0f")
                       + " mm Kantenlaenge.",),
            )

        full = arrangements.generate(arrangement_id, request)
        notes = list(full.notes)
        capacity = full.count
        if capacity == 0:
            return SuctionLayout(
                arrangement_id=arrangement_id,
                notes=tuple(notes) or ("Mit diesem Muster laesst sich auf der Platte kein Sauger unterbringen.",),
            )

        target = wanted_count
        if target <= 0 and capacity > MAX_CUP_POSITIONS:
            # Die Hoechstbestueckung waere unrealistisch gross. Statt zu
            # scheitern wird auf die Grenze zurueckgesetzt und das gemeldet.
            notes.append(
                "Die Platte wuerde " + str(capacity) + " Sauger aufnehmen. Gerechnet wird "
                "mit " + str(MAX_CUP_POSITIONS) + " - fuer mehr bitte die Saugeranzahl "
                "ausdruecklich vorgeben."
            )
            target = MAX_CUP_POSITIONS

        if 0 < target < capacity:
            result = self._thin_to(arrangement_id, request, target)
        else:
            result = full
            if 0 < target != capacity:
                notes.append(
                    "Gewuenscht waren " + str(target) + " Sauger; mit dem Muster '"
                    + arrangements.label_of(arrangement_id) + "' passen auf diese Platte "
                    "hoechstens " + str(capacity) + "."
                )

        return SuctionLayout(
            placements=self._to_placements(result.centers, cup.id),
            arrangement_id=arrangement_id,
            columns=result.columns,
            rows=result.rows,
            max_count=capacity,
            pitch_x_mm=result.pitch_x_mm,
            pitch_y_mm=result.pitch_y_mm,
            notes=tuple(notes),
        )

    @staticmethod
    def _to_placements(
        centers: tuple[tuple[float, float], ...], cup_id: str
    ) -> tuple[SuctionPlacement, ...]:
        """Nummeriert die Mittelpunkte durch: erst nach Reihe, dann nach Spalte.

        Die feste Reihenfolge macht zwei Laeufe vergleichbar und die Nummern in
        der Zeichnung stabil (Spezifikation 39).
        """
        ordered = sorted(centers, key=lambda c: (round(c[1], 6), round(c[0], 6)))
        rows = sorted({round(y, 6) for _x, y in ordered})
        row_index = {y: i for i, y in enumerate(rows)}

        placements: list[SuctionPlacement] = []
        column_counter: dict[int, int] = {}
        for index, (x, y) in enumerate(ordered):
            row = row_index[round(y, 6)]
            column = column_counter.get(row, 0)
            column_counter[row] = column + 1
            placements.append(
                SuctionPlacement(
                    index=index, center_x_mm=x, center_y_mm=y, cup_id=cup_id,
                    row_index=row, column_index=column, active=True,
                )
            )
        return tuple(placements)


#: Wieviele Paketreihen der Zeichenbereich ueber jede Plattenkante hinausreicht.
#:
#: Der Bereich ist BEWUSST von der gewuenschten Stueckzahl unabhaengig. Ihn mit
#: der Stueckzahl wachsen zu lassen liegt nahe, zerstoert aber genau das, was
#: eine solche Anzeige leisten soll: bei jeder Aenderung entsteht das Muster auf
#: einer anderen Flaeche neu, die Pakete springen, und von der vorigen Anordnung
#: bleibt nichts stehen. Gemessen: beim Wechsel von vier auf fuenf Pakete
#: behielt kein einziges seine Position.
#:
#: Mit fester Flaeche steht die Reihenfolge ein fuer alle Mal fest. Eine hoehere
#: Stueckzahl nimmt genau dieselben Pakete wie vorher und legt weitere aussen
#: an: die Ladung waechst von innen nach aussen.
#:
#: Der Bereich waechst dabei in GANZEN Paketen von der Plattenkante aus. Ohne
#: das faellt die Plattenkante mitten in eine Rasterzelle, und unter die Platte
#: passt eine Reihe weniger, als hineinpassen wuerde - bei 600 mm Platte und
#: 150 mm Paket drei statt vier.
LAYOUT_EXTRA_RINGS = 16

#: Obergrenze der erzeugten Positionen. Bei sehr kleinen Paketen auf einer
#: grossen Platte kaemen sonst Zehntausende zusammen. Die Begrenzung haengt nur
#: von Platte und Paket ab, nicht von der Stueckzahl - die Reihenfolge bleibt
#: also stabil.
MAX_LAYOUT_POSITIONS = 5000

#: Reicht der Bereich fuer die gewuenschte Zahl doch nicht - etwa beim
#: Ringstapel, der seinen Kern frei laesst -, waechst er schrittweise nach.
PACKAGE_AREA_GROWTH = 1.5
PACKAGE_AREA_STEPS = 6


def package_layout(
    package: PackageSpec,
    plate: VacuumPlateSpec,
    count: int,
    strategy: str = "uniform_grid",
    gap_mm: float = 0.0,
) -> tuple[tuple[Footprint, ...], tuple[str, ...]]:
    """Ordnet die zu hebenden Pakete an - notfalls groesser als die Platte.

    Dieselbe Musterschicht wie die Palettierung (Spezifikation 18): das dort
    gewaehlte Muster bestimmt auch hier die Anordnung.

    Die Platte begrenzt die Anordnung NICHT. Eine Saugerplatte ist regelmaessig
    kleiner als das, was sie hebt: sie greift in die Mitte der Lage, und die
    aeusseren Kartons ragen darueber hinaus. Wuerde die Plattengroesse die
    Paketanordnung beschneiden, liesse sich genau dieser Regelfall nicht
    rechnen.

    Aufgebaut wird von innen nach aussen und dabei WAAGERECHT: was nicht mehr
    unter die Platte passt, legt sich seitlich an, nicht darueber und darunter
    (siehe _innermost()). Das Muster entsteht einmal auf einem festen, mittig
    zur Platte liegenden Bereich; ausgewaehlt werden daraus die Pakete, die der
    Plattenmitte am naechsten liegen. Eine hoehere Stueckzahl nimmt deshalb
    genau dieselben Pakete wie vorher und legt weitere aussen an - die Anordnung
    waechst, statt sich neu zu wuerfeln.

    Zum Schluss wird die Auswahl mittig zur Platte gerueckt. Ein Greifer setzt
    ueber dem Schwerpunkt dessen an, was er hebt; eine seitlich haengende
    Ladung waere nicht nur unschoen, sondern falsch.
    """
    if count <= 0:
        return (), ()

    span_l, span_w = _layout_span(package, plate, gap_mm)

    layout = None
    for _ in range(PACKAGE_AREA_STEPS + 1):
        layout = generate_pattern(
            strategy,
            PatternRequest(
                bounds_length_mm=span_l, bounds_width_mm=span_w,
                item_length_mm=package.length_mm, item_width_mm=package.width_mm,
                gap_mm=gap_mm,
            ),
        )
        if layout.count >= count:
            break
        span_l *= PACKAGE_AREA_GROWTH
        span_w *= PACKAGE_AREA_GROWTH

    notes = list(layout.notes) if layout else []
    if layout is None or not layout.footprints:
        return (), (
            "Das Paket " + format(package.length_mm, ".0f") + " x "
            + format(package.width_mm, ".0f") + " mm laesst sich mit diesem Muster nicht anordnen.",
        )

    selected = _innermost(layout.footprints, span_l, span_w, plate, count, gap_mm)
    if len(selected) < count:
        notes.append(
            "Mit diesem Muster lassen sich " + str(len(selected)) + " Pakete anordnen, "
            "angefordert waren " + str(count) + "."
        )

    selected = _recenter(selected, plate)
    ordered = tuple(sorted(selected, key=lambda f: (round(f.y_mm, 6), round(f.x_mm, 6))))

    overhanging = sum(
        1 for f in ordered
        if not rect_contains_rect(
            0.0, 0.0, plate.length_mm, plate.width_mm,
            f.x_mm, f.y_mm, f.length_mm, f.width_mm,
            tolerance_mm=PLACEMENT_TOLERANCE_MM,
        )
    )
    if overhanging:
        notes.append(
            str(overhanging) + " von " + str(len(ordered)) + " Paketen ragen ueber die Platte "
            "hinaus. Dort koennen keine Sauger sitzen - fuer die Haltekraft zaehlt nur, was "
            "unter der Platte liegt."
        )

    return ordered, tuple(notes)


def _layout_span(
    package: PackageSpec, plate: VacuumPlateSpec, gap_mm: float
) -> tuple[float, float]:
    """Zeichenbereich der Paketanordnung: die Platte plus ganze Paketreihen.

    In ganzen Paketen von der Plattenkante aus, damit das Raster kantenbuendig
    zur Platte liegt. Ein beliebig grosser Bereich wuerde in der Mitte
    zentriert, und die Plattenkante fiele mitten in eine Zelle - unter die
    Platte passte dann eine Reihe weniger als moeglich.

    Die Zahl der Zusatzreihen wird verkleinert, falls sonst zu viele Positionen
    entstuenden. Sie haengt allein von Platte und Paket ab, nicht von der
    gewuenschten Stueckzahl; die Auswahlreihenfolge bleibt damit stabil.
    """
    cell_l = max(1e-6, package.length_mm + gap_mm)
    cell_w = max(1e-6, package.width_mm + gap_mm)

    rings = LAYOUT_EXTRA_RINGS
    while rings > 1:
        columns = plate.length_mm / cell_l + 2 * rings
        rows = plate.width_mm / cell_w + 2 * rings
        if columns * rows <= MAX_LAYOUT_POSITIONS:
            break
        rings -= 1

    return (
        plate.length_mm + 2 * rings * cell_l,
        plate.width_mm + 2 * rings * cell_w,
    )


def _innermost(
    footprints: tuple[Footprint, ...],
    span_l_mm: float,
    span_w_mm: float,
    plate: VacuumPlateSpec,
    count: int,
    gap_mm: float = 0.0,
) -> tuple[Footprint, ...]:
    """Die count Pakete, die als erste belegt werden.

    Zuerst alles, was vollstaendig unter der Platte liegt, danach der Rest -
    beides jeweils von innen nach aussen. Unter der Platte laesst sich nur
    greifen, was auch darunter liegt; deshalb steht diese Frage vor jeder
    anderen.

    Gemessen wird in RASTERZELLEN, nicht in Millimetern. Der Abstand in
    Millimetern klingt richtiger, als er ist: bei einem Paket 200 x 150 mm liegt
    die naechste Reihe 150 mm entfernt, die naechste Spalte 200 mm. Die Reihe
    gewinnt damit jedesmal, und die Ladung waechst zu einem hohen schmalen
    Stapel ueber und unter der Platte, waehrend links und rechts Platz bleibt.
    Mit dem Zellmass als Einheit ist ein Schritt ein Schritt - in welche
    Richtung er geht, entscheidet nicht mehr das Seitenverhaeltnis des Kartons.

    Bei gleichem Abstand waechst die Ladung WAAGERECHT. Der Gleichstand ist
    dabei nicht die Ausnahme, sondern der Regelfall: in Zellen gemessen ist ein
    Spaltenschritt genauso weit wie ein Reihenschritt, die naechste Spalte und
    die naechste Reihe liegen also gleich weit von der Mitte. Wer dann
    gewinnen soll, steht im zweiten Schluessel - die Position naeher an der
    Mittelreihe, und das ist die seitliche. Bei einer Platte fuer 2 x 2 Pakete
    entstehen so 3 x 2 und 4 x 2, statt 2 x 3 und 2 x 4.

    Waagerecht heisst nicht "um jeden Preis": eine Spalte weit draussen liegt
    auch in Zellen gemessen weiter weg als die naechste Reihe und kommt deshalb
    spaeter. Die Ladung wird breiter als hoch, aber kein Band.

    Zuletzt entscheidet die Lage selbst, und hier laufen die beiden Bereiche
    auseinander:

    UNTER der Platte erst y, dann x - die Reihe wird von links nach rechts
    aufgefuellt, bevor die naechste beginnt. Die vier Plaetze unter einer Platte
    fuer 2 x 2 Pakete sind gleich weit von der Mitte entfernt; zwei Pakete
    sollen dort nebeneinander liegen und nicht uebereinander.

    AUSSERHALB erst x, dann y - die angefangene Spalte wird fertig, bevor die
    naechste beginnt. Sonst legen sich das fuenfte und sechste Paket links und
    rechts an dieselbe Reihe, die Gruppe steht als T ueber der Platte, und weil
    sie anschliessend nach ihrem Schwerpunkt gerueckt wird, rutscht sie um eine
    halbe Paketbreite: unter der untersten Saugerreihe liegt dann kein Karton
    mehr. Spaltenweise bleibt aus 4 + 2 ein geschlossenes Rechteck aus 3 x 2.

    Die Reihenfolge haengt nur von der Geometrie ab, nicht von count - deshalb
    ist die Auswahl fuer count+1 eine echte Obermenge der Auswahl fuer count.
    Genau das macht das Wachsen von innen nach aussen aus. Sie ist zugleich
    eindeutig, das Ergebnis also reproduzierbar (Spezifikation 39).
    """
    center_x = span_l_mm / 2.0
    center_y = span_w_mm / 2.0
    plate_x0 = center_x - plate.length_mm / 2.0
    plate_y0 = center_y - plate.width_mm / 2.0
    cell_l, cell_w = _cell_size(footprints, gap_mm)

    def order(footprint: Footprint) -> tuple[int, float, float, float, float]:
        under_plate = rect_contains_rect(
            plate_x0, plate_y0, plate.length_mm, plate.width_mm,
            footprint.x_mm, footprint.y_mm, footprint.length_mm, footprint.width_mm,
            tolerance_mm=PLACEMENT_TOLERANCE_MM,
        )
        dx = (footprint.x_mm + footprint.length_mm / 2.0 - center_x) / cell_l
        dy = (footprint.y_mm + footprint.width_mm / 2.0 - center_y) / cell_w
        x, y = round(footprint.x_mm, 6), round(footprint.y_mm, 6)
        return (
            0 if under_plate else 1,
            round(dx * dx + dy * dy, 6),
            round(dy * dy, 6),
            *((y, x) if under_plate else (x, y)),
        )

    return tuple(sorted(footprints, key=order)[:count])


def _cell_size(footprints: tuple[Footprint, ...], gap_mm: float) -> tuple[float, float]:
    """Das Rastermass der Anordnung: ein Schritt nach rechts, einer nach oben.

    Aus den Paketen selbst und nicht aus dem PackageSpec, weil ein Muster seine
    Pakete drehen darf - im Querverband ist die Zelle dann so breit, wie das
    Paket lang ist. Der Median trifft auch die Muster, die beide Ausrichtungen
    mischen, und laesst sich von einem einzelnen Randstueck nicht verziehen.
    """
    if not footprints:
        return 1.0, 1.0
    cell_l = median(f.length_mm for f in footprints) + gap_mm
    cell_w = median(f.width_mm for f in footprints) + gap_mm
    return max(cell_l, 1e-6), max(cell_w, 1e-6)


def _recenter(footprints: tuple[Footprint, ...], plate: VacuumPlateSpec) -> tuple[Footprint, ...]:
    """Rueckt die Paketgruppe so, dass ihr Schwerpunkt in der Plattenmitte liegt.

    Nach dem SCHWERPUNKT, nicht nach dem umschliessenden Rechteck. Der
    Unterschied wird sichtbar, sobald die Gruppe nicht symmetrisch ist: vier
    gleiche Pakete in L-Form haben ihren Schwerpunkt nicht in der Mitte ihres
    Rechtecks. Nach dem Rechteck gerueckt haengt die Last dann seitlich am
    Greifer und erzeugt ein Kippmoment - gemessen bis zu einer halben
    Paketlaenge Versatz.

    Alle Pakete sind gleich schwer, der Flaechenschwerpunkt ist also zugleich
    der Massenschwerpunkt.

    Die Verschiebung ist fuer alle Pakete dieselbe. Die Anordnung untereinander
    bleibt damit unberuehrt - eine hoehere Stueckzahl verschiebt die Gruppe
    hoechstens um ein Stueck, statt sie neu zu wuerfeln.
    """
    if not footprints:
        return footprints

    centroid_x = sum(f.x_mm + f.length_mm / 2.0 for f in footprints) / len(footprints)
    centroid_y = sum(f.y_mm + f.width_mm / 2.0 for f in footprints) / len(footprints)
    offset_x = plate.length_mm / 2.0 - centroid_x
    offset_y = plate.width_mm / 2.0 - centroid_y

    return tuple(
        Footprint(f.x_mm + offset_x, f.y_mm + offset_y, f.length_mm, f.width_mm, f.rotated)
        for f in footprints
    )
