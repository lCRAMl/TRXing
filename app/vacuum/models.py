"""Datenobjekte der Vakuumplatte und ihrer Sauger.

Zum Vorzeichen: Unterdruck wird durchgaengig als positive Druckdifferenz zur
Umgebung gefuehrt (vacuum_pa). Die im Datenblatt uebliche Schreibweise -0,6 bar
entspricht hier 60000 Pa. Siehe app/domain/units.py.

Zum Arbeitspunkt: die Anwendung rechnet nicht mit dem eingestellten Sollvakuum,
sondern loest den Schnittpunkt aus Pumpenkennlinie und Leckagebedarf. Ein
offener Sauger senkt damit das erreichbare Vakuum und dadurch die Haltekraft,
statt nur eine Warnung zu erzeugen.

Zusammengelegt aus dto/suction.py und dto/vacuum.py - der Sauger und die
Platte, auf der er sitzt, gehoeren in dieselbe Scheibe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from dataclasses import dataclass, field
from app.domain.results import Status
from app.domain.results import FrozenTrace
from app.domain.units import GRAVITY_MS2, STANDARD_AMBIENT_PA
from app.domain.results import CalculationMeta
from app.domain.geometry import Footprint
from app.domain.package import PackageSpec


# ---------------------------------------------------------------------------
# suction.py
# ---------------------------------------------------------------------------
"""Datenobjekte der Saugnaepfe.

Zur Herkunft der Kennwerte - Spezifikation 25 verlangt, dass jeder Wert
zuordenbar ist:

Aus dem Datenblatt SPB2 (2.5 Folds) uebernommen sind theoretical_force_n,
pull_off_force_n, lateral_force_n, volume_cm3, min_workpiece_radius_mm,
hose_inner_diameter_mm sowie die Geometrie d2, Ds, Dmax(S), dn und der Hub.

effective_diameter_mm ist d2, der innere Faltendurchmesser aus der
Konstruktionstabelle. Bei der Baureihe SPB2 reproduziert seine Kreisflaeche die
angegebene Saugkraft nahezu exakt:

    SPB2 20   d2 12,0 mm -> 6,79 N   (Datenblatt 6,8 N)
    SPB2 25   d2 14,5 mm -> 9,91 N   (Datenblatt 9,9 N)
    SPB2 30   d2 16,9 mm -> 13,46 N  (Datenblatt 14,4 N)
    SPB2 40   d2 22,9 mm -> 24,71 N  (Datenblatt 24,8 N)
    SPB2 50   d2 27,1 mm -> 34,61 N  (Datenblatt 34,6 N)

Bei den uebrigen Baureihen gilt das NICHT. SPB1 liegt durchgehend rund zehn
Prozent daneben, SPB4 zwischen +7 und -15 Prozent, und SPB2f in den Groessen 30
bis 50 um -46 bis -81 Prozent - dort ist d2 konstruktiv gar nicht die
kraftuebertragende Flaeche.

Deshalb geht d2 in KEIN Ergebnis ein. Gerechnet wird ausschliesslich mit der
zurueckgerechneten Flaeche aus der Datenblattkraft (siehe datasheet_area_mm2);
die kommt beim Bezugsdruck exakt auf den Herstellerwert und skaliert
physikalisch richtig auf andere Vakuumniveaus. d2 dient nur der Gegenprobe, und
deren Ergebnis wird im Rechenweg ausgewiesen.

NICHT aus dem Datenblatt stammen Ausflussbeiwert, Strombegrenzer und
Kartonpermeabilitaet. Die stehen in der Konfiguration und werden in der
Oberflaeche als Annahme gekennzeichnet.
"""

@dataclass(frozen=True, slots=True)
class SuctionCupSpec:
    """Ein Saugertyp aus config/suction_cups.json."""

    id: str
    name: str
    manufacturer: str
    family: str

    #: Nenngroesse der Baureihe (20/25/30/40/50), nicht die wirksame Flaeche.
    nominal_diameter_mm: float

    #: d2 - innerer Faltendurchmesser. Traegt die wirksame Saugflaeche.
    effective_diameter_mm: float

    #: Ds - Durchmesser der Dichtlippe. Entscheidet, ob der Sauger dichtet.
    sealing_lip_diameter_mm: float

    #: Dmax(S) - Aussenmass unter Vakuum. Bestimmt den Mindestrasterabstand.
    outer_diameter_mm: float

    #: dn - Bohrung des Anschlusses. Bestimmt den Fremdluftstrom offener Sauger.
    bore_diameter_mm: float

    #: Theoretische Saugkraft beim Bezugsdruck. Datenblattwert.
    theoretical_force_n: float

    #: Unterdruck, auf den sich theoretical_force_n bezieht. Schmalz nennt
    #: -0,6 bar; andere Hersteller beziehen auf -0,7 bar oder -0,8 bar. Der
    #: Bezug gehoert deshalb zum Kennwert und wird nicht im Programm festgelegt.
    reference_vacuum_pa: float = 60000.0

    pull_off_force_n: float = 0.0
    lateral_force_n: float = 0.0
    volume_cm3: float = 0.0
    min_workpiece_radius_mm: float = 0.0
    hose_inner_diameter_mm: float = 0.0
    stroke_mm: float = 0.0
    material: str = ""
    folds_count: float = 0.0
    datasheet_url: str = ""

    @property
    def effective_area_mm2(self) -> float:
        """Wirksame Saugflaeche aus d2."""
        r = self.effective_diameter_mm / 2.0
        return math.pi * r * r

    @property
    def sealing_area_mm2(self) -> float:
        """Flaeche, die der Dichtlippenring umschliesst."""
        r = self.sealing_lip_diameter_mm / 2.0
        return math.pi * r * r

    @property
    def bore_area_mm2(self) -> float:
        r = self.bore_diameter_mm / 2.0
        return math.pi * r * r

    @property
    def datasheet_area_mm2(self) -> float:
        """Wirksame Flaeche, aus der Datenblattkraft zurueckgerechnet.

        A = F / dp_ref. Beim Bezugsdruck liefert sie exakt den Herstellerwert,
        bei anderem Unterdruck skaliert sie physikalisch richtig. Das ist die
        Flaeche, mit der das Kraftmodell rechnet.
        """
        if self.theoretical_force_n <= 0.0 or self.reference_vacuum_pa <= 0.0:
            return self.effective_area_mm2
        return self.theoretical_force_n / self.reference_vacuum_pa * 1_000_000.0

    @property
    def effective_force_diameter_mm(self) -> float:
        """Durchmesser des Kreises, der die wirksame Flaeche hat.

        Der Wirkungsbereich, den die Draufsicht zeichnet. Er ist deutlich
        kleiner als der Sauger selbst: bei SPB2 30 stehen 16,9 mm Wirkkreis
        einer Dichtlippe von 31,4 mm gegenueber. Wer nur den sichtbaren Sauger
        betrachtet, ueberschaetzt die Haltekraft erheblich - deshalb wird
        beides getrennt dargestellt.
        """
        area = self.datasheet_area_mm2
        return 2.0 * math.sqrt(area / math.pi) if area > 0.0 else 0.0

    @property
    def force_area_deviation_pct(self) -> float:
        """Abweichung zwischen Datenblattkraft und Kraft aus der d2-Flaeche.

        Null bedeutet vollstaendige Uebereinstimmung; ein Wert ungleich null
        wird im Trace als Hinweis ausgegeben.
        """
        if self.theoretical_force_n <= 0.0:
            return 0.0
        geometric = self.reference_vacuum_pa * self.effective_area_mm2 / 1_000_000.0
        return (geometric - self.theoretical_force_n) / self.theoretical_force_n * 100.0


class RestrictorMode(Enum):
    """Was zwischen Sauger und Vakuumleitung sitzt.

    Ohne Begrenzung zieht ein offener Sauger bei -0,6 bar durch seine Bohrung
    einen kritischen Luftstrom in der Groessenordnung mehrerer Kubikmeter pro
    Stunde - genug, um das Vakuum der ganzen Platte zusammenbrechen zu lassen.
    Strombegrenzer und Rueckschlagventile sind deshalb keine Feinheit, sondern
    der uebliche Aufbau. Das Datenblatt nennt dazu keine Werte, die Angaben
    stammen aus der Konfiguration.
    """

    NONE = "none"
    ORIFICE = "orifice"
    CHECK_VALVE = "check_valve"

    @property
    def label(self) -> str:
        return {
            RestrictorMode.NONE: "Ohne Begrenzung (volle Bohrung)",
            RestrictorMode.ORIFICE: "Strombegrenzer (Drossel)",
            RestrictorMode.CHECK_VALVE: "Rueckschlagventil (schliesst bei offenem Sauger)",
        }[self]


@dataclass(frozen=True, slots=True)
class RestrictorSpec:
    """Strombegrenzung je Saugerposition. Keine Datenblattgroesse."""

    mode: RestrictorMode = RestrictorMode.NONE

    #: Engster Querschnitt der Drossel. Nur bei mode ORIFICE wirksam.
    diameter_mm: float = 1.0

    #: Restleckage eines geschlossenen Rueckschlagventils, als Anteil des
    #: ungedrosselten Stroms. Kein Ventil schliesst vollstaendig.
    check_valve_leak_ratio: float = 0.02

    #: Ausflussbeiwert der Bohrung. Modellannahme, kein Datenblattwert.
    discharge_coefficient_factor: float = 0.8


class ContactClass(Enum):
    """Zustand eines Saugers gegenueber dem Paket.

    SEALED  Dichtlippe vollstaendig auf der Kartonflaeche - der Sauger traegt.
    PARTIAL Dichtlippe nur teilweise auf dem Karton. Er beruehrt das Paket,
            dichtet aber nicht; physikalisch leckt er wie ein offener Sauger.
            Die Klasse bleibt trotzdem getrennt, weil sie dem Benutzer zeigt,
            dass ein anderes Raster das Problem loesen wuerde.
    OPEN    Kein Karton unter dem Sauger - volle Fremdluft.
    """

    SEALED = "sealed"
    PARTIAL = "partial"
    OPEN = "open"

    @property
    def label(self) -> str:
        return {
            ContactClass.SEALED: "Wirksam",
            ContactClass.PARTIAL: "Teilweise aufliegend",
            ContactClass.OPEN: "Offen",
        }[self]


@dataclass(frozen=True, slots=True)
class SuctionPlacement:
    """Ein Sauger auf der Platte."""

    index: int
    center_x_mm: float
    center_y_mm: float
    cup_id: str
    row_index: int = 0
    column_index: int = 0
    active: bool = True


@dataclass(frozen=True, slots=True)
class CupContact:
    """Geometrisches Ergebnis der Ueberdeckungspruefung eines Saugers."""

    placement_index: int
    contact: ContactClass
    covered_area_mm2: float = 0.0
    coverage_ratio: float = 0.0
    effective_area_mm2: float = 0.0
    package_index: int = -1


# ---------------------------------------------------------------------------
# vacuum.py
# ---------------------------------------------------------------------------
"""Datenobjekte der Vakuumplatte.

Zum Vorzeichen: Unterdruck wird durchgaengig als positive Druckdifferenz zur
Umgebung gefuehrt (vacuum_pa). Die im Datenblatt uebliche Schreibweise -0,6 bar
entspricht hier 60000 Pa. Siehe app/domain/units.py.

Zum Arbeitspunkt: die Anwendung rechnet nicht mit dem eingestellten Sollvakuum,
sondern loest den Schnittpunkt aus Pumpenkennlinie und Leckagebedarf. Ein
offener Sauger senkt damit das erreichbare Vakuum und dadurch die Haltekraft -
statt nur eine Warnung zu erzeugen, waehrend das Ergebnis weiter mit dem
Sollvakuum glaenzt. Das Sollvakuum bleibt als Vergleichswert erhalten.
"""

#: Die Rastermasse der Schmalz-Leichtbau-Lagengreifer ZLW, als (Code, mm).
#:
#: Die Bestelltabelle der Baureihe fuehrt sie unter der Spaltenueberschrift
#: "Abstand der Saugstellen in mm"; die einzelnen Varianten nennen die
#: Anordnung "Dreieck, 30 mm" beziehungsweise "Dreieck, 45 mm". Es ist also
#: dasselbe Dreiecksgitter, das die dichteste Packung ohnehin legt - vorgegeben
#: ist allein das Rastermass.
#:
#: WELCHER Abstand die Zahl ist, sagt die Quelle nicht. Entschieden wird es
#: durch ein Geraet, das es wirklich gibt: ZLW FL 850x650 SE SPB2 40 45T. Der
#: SPB2 40 hat Dmax(S) = 44,5 mm. Als MITTENabstand gelesen bleiben in einem
#: 45-mm-Raster 0,5 mm Luft, und die Bauform geht auf; als lichter Abstand
#: gelesen waere der Mittenabstand 89,5 mm, und das Geraet gaebe es nicht.
#:
#: Quelle: www.schmalz.com, Produktseite "Leichtbau-Lagengreifer ZLW",
#: Abschnitte "Bestellinformationen" und "Technische Daten".
SCHMALZ_RASTER: tuple[tuple[str, float], ...] = (
    ("20T", 20.0),
    ("30T", 30.0),
    ("45T", 45.0),
)


@dataclass(frozen=True, slots=True)
class VacuumPlateSpec:
    """Geometrie der Saugerplatte."""

    length_mm: float
    width_mm: float
    thickness_mm: float = 15.0

    #: Abstand der aeussersten Saugermitten zum Plattenrand.
    edge_margin_mm: float = 20.0

    #: Lichter Mindestabstand zwischen zwei Saugeraussenkanten.
    #:
    #: Nur noch die Grundlage des Rastermasses "automatisch". Sobald
    #: raster_pitch_mm gesetzt ist, steht der lichte Abstand nicht mehr am
    #: Anfang der Rechnung, sondern faellt als Ergebnis hinten heraus:
    #: Rastermass minus Aussenmass. Er kann dann auch negativ werden.
    min_spacing_mm: float = 5.0

    #: Vorgegebener Mittenabstand zweier Sauger. 0 heisst: aus dem Sauger
    #: gerechnet, also Aussenmass unter Vakuum plus min_spacing_mm.
    #:
    #: Das ist die Stelle, an der die Schmalz-Bauformen 20T/30T/45T eingreifen
    #: (siehe SCHMALZ_RASTER). Ein Wert kleiner als das Aussenmass des Saugers
    #: ist ERLAUBT - die Sauger ueberlappen sich dann, und die Verteilung meldet
    #: es als Warnung. Gezeichnet wird trotzdem, damit sich das Raster ansehen
    #: laesst.
    raster_pitch_mm: float = 0.0

    @property
    def raster_label(self) -> str:
        """Die Schmalz-Kennzeichnung des eingestellten Rastermasses.

        Leer, wenn das Mass keiner Bauform entspricht - dann ist es ein freies
        Raster, und es waere falsch, ihm einen Herstellercode anzuhaengen.
        """
        for code, pitch_mm in SCHMALZ_RASTER:
            if abs(pitch_mm - self.raster_pitch_mm) < 1e-9:
                return code
        return ""

    @property
    def area_mm2(self) -> float:
        return self.length_mm * self.width_mm


class LeakageModel(Enum):
    """Modelltyp fuer den Luftdurchtritt durch den Karton.

    Die Permeabilitaet ist keine Naturkonstante und wird hier auch nicht als
    solche behandelt (Spezifikation 22): der Benutzer gibt sie vor, das Modell
    bestimmt nur, wie daraus ein Volumenstrom wird.

    NONE            dichter Karton, kein Durchtritt
    CONSTANT        fester Strom je wirksamem Sauger, unabhaengig vom Druck
    FLOW_PER_AREA   Strom je wirksamer Flaeche bei Bezugsdruck, ueber das
                    Druckverhaeltnis mit dem Exponenten skaliert
    PRESSURE_LINEAR Strom proportional zu Flaeche und Druckdifferenz (Darcy)
    """

    NONE = "none"
    CONSTANT = "constant"
    FLOW_PER_AREA = "flow_per_area"
    PRESSURE_LINEAR = "pressure_linear"

    @property
    def label(self) -> str:
        return {
            LeakageModel.NONE: "Dicht (kein Durchtritt)",
            LeakageModel.CONSTANT: "Konstanter Strom je Sauger",
            LeakageModel.FLOW_PER_AREA: "Strom je Flaeche bei Bezugsdruck",
            LeakageModel.PRESSURE_LINEAR: "Druckproportional (Darcy)",
        }[self]


@dataclass(frozen=True, slots=True)
class RasterOverview:
    """Was die Oberflaeche ueber das eingestellte Raster anzeigt.

    Drei Zahlen und die Hinweise dazu, in einem Zug geholt. Einzeln abgefragt
    wuerde die Verteilung dreimal durchgerechnet - und das bei jedem
    Tastendruck in einem Plattenmass.

    Gerechnet wird all das in der Engine, nicht im Tab (Spezifikation 37). Der
    lichte Abstand ist hier ausdruecklich ein ERGEBNIS: er faellt aus dem
    Rastermass heraus, statt es zu bestimmen, und darf negativ sein.
    """

    #: Mittenabstand, mit dem tatsaechlich verteilt wird.
    pitch_mm: float = 0.0

    #: Rastermass minus Aussenmass. Negativ heisst Ueberlappung.
    clearance_mm: float = 0.0

    #: Das Rastermass, das sich allein aus dem Sauger ergaebe - der Wert
    #: hinter der Einstellung "automatisch".
    automatic_pitch_mm: float = 0.0

    #: Kleinstes Rastermass, das sich fuer diesen Sauger einstellen laesst.
    #: Die Oberflaeche setzt damit die Untergrenze ihres Eingabefelds.
    min_pitch_mm: float = 0.0

    #: Hoechstzahl der Sauger mit diesem Raster und diesem Muster.
    max_cup_count: int = 0

    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeakageSpec:
    """Parameter des gewaehlten Permeabilitaetsmodells.

    permeability_value wird je nach Modell verschieden gelesen; unit_label sagt,
    wie. Die Oberflaeche zeigt beides an, damit aus der Zahl allein kein
    scheinbar exakter Kennwert wird.
    """

    model: LeakageModel = LeakageModel.NONE
    permeability_value: float = 0.0
    unit_label: str = ""
    reference_vacuum_pa: float = 60000.0

    #: Exponent der Druckskalierung bei FLOW_PER_AREA. 1,0 ist laminar,
    #: 0,5 turbulent. Modellannahme, kein Messwert.
    pressure_exponent_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class SystemVolumeSpec:
    """Das Volumen, das leergesaugt werden muss.

    Ohne diese Angabe gibt es keine Zeitachse: die Evakuierzeit haengt am
    Volumen, nicht an der Plattenflaeche. Alle vier Werte sind
    Anlagenangaben und stehen in keinem Datenblatt.

    Der Schlauchdurchmesser geht NUR ins Volumen ein. Ein Druckverlust im
    Schlauch wird nicht gerechnet - ein dickerer Schlauch macht die Platte in
    diesem Modell also langsamer, nicht schneller. In Wirklichkeit ist beides
    wahr, und bei DN 100 fuer 510 m3/h (rund 18 m/s) ueberwiegt das Volumen.

    `extra_volume_l` ist der Platz fuer das, was das Datenblatt nicht nennt:
    das Innere der Sauger. Bei 391 Balgsaugern ist das kein kleiner Posten,
    aber Schmalz nennt kein Balgvolumen - geschaetzt wird hier nichts.
    Vorgabe 0; dann ist die gerechnete Zeit eher zu kurz als falsch.
    """

    box_height_mm: float = 80.0
    hose_length_m: float = 10.0
    hose_diameter_mm: float = 100.0
    extra_volume_l: float = 0.0


@dataclass(frozen=True, slots=True)
class EvacuationPoint:
    """Ein Punkt des Vakuumverlaufs."""

    time_s: float
    vacuum_pa: float
    pump_flow_m3s: float
    leak_m3s: float


@dataclass(frozen=True, slots=True)
class EvacuationCurve:
    """Der Vakuumverlauf ueber der Zeit, bei EINER Frequenz."""

    points: tuple[EvacuationPoint, ...] = ()

    box_volume_m3: float = 0.0
    hose_volume_m3: float = 0.0
    extra_volume_m3: float = 0.0

    frequency_hz: float = 50.0
    #: Saugvermoegen und Endvakuum des Erzeugers BEI DIESER FREQUENZ.
    nominal_flow_m3s: float = 0.0
    max_vacuum_pa: float = 0.0

    #: Der Arbeitspunkt: dort halten sich Angebot und Leckage die Waage.
    final_vacuum_pa: float = 0.0
    time_to_90_s: float = 0.0
    time_to_99_s: float = 0.0

    notes: tuple[str, ...] = ()

    @property
    def volume_m3(self) -> float:
        return self.box_volume_m3 + self.hose_volume_m3 + self.extra_volume_m3

    @property
    def duration_s(self) -> float:
        return self.points[-1].time_s if self.points else 0.0


@dataclass(frozen=True, slots=True)
class SharedPlate:
    """Die zuletzt gerechnete Platte, fuer andere Ansichten bereitgelegt.

    Dasselbe Verfahren wie bei der Lage der Palettierung (SharedLayer): der
    Dienst, der das Ergebnis erzeugt hat, legt es bereit, und wer es braucht,
    holt es dort ab. Der Vakuumverlauf rechnet damit auf GENAU der Platte, die
    nebenan angezeigt wird - er baut sich keine zweite aus denselben
    Eingaben zusammen.
    """

    request: "VacuumInput"
    result: "VacuumResult"


#: Arbeitspunkte der Schmalz-Seitenkanalgeblaese bei 50 Hz: (m3/h, mbar).
#:
#: Kein Pumpenkatalog - das waere eine Geraeteliste, die gepflegt werden muss.
#: Hier stehen nur die ARBEITSPUNKTE, und zwar die, die es wirklich gibt.
#: Ausgelesen aus der Schmalz-Uebersicht (doc/pumps.html, 41 Geraete, davon 28
#: mit 50-Hz-Angaben); die 28 Geraete teilen sich 14 verschiedene Punkte:
#:
#:      m3/h   mbar    kW    Geraete
#:        75    105  0,37      1
#:        90    330  1,5       2
#:       130    125  0,75      2
#:       180    215  1,5       2
#:       195    440  3,0       2
#:       260    410  4,0       3
#:       260    445  4,0       1
#:       325    265  3,0       2
#:       375    390  5,5       2
#:       390    315  4,0       2
#:       510    200  4,0       2
#:       510    390 11,0       3     <- Vorgabe, der haeufigste Punkt
#:       765    280  7,5       2
#:      1050    290 11,0       2
#:
#: Als PAAR und nicht als zwei Listen: 510 m3/h gibt es bei 200 UND bei
#: 390 mbar, 260 m3/h bei 410 und bei 445. Zwei getrennte Auswahlfelder
#: koennten daraus Kombinationen bauen, die kein Geraet hat.
#:
#: Die Leistung in kW steht nur hier im Kommentar: sie erklaert, warum
#: dieselben 510 m3/h einmal 4 und einmal 11 kW kosten, geht aber in keine
#: Rechnung ein.
SCHMALZ_OPERATING_POINTS: tuple[tuple[float, float], ...] = (
    (75.0, 105.0),
    (90.0, 330.0),
    (130.0, 125.0),
    (180.0, 215.0),
    (195.0, 440.0),
    (260.0, 410.0),
    (260.0, 445.0),
    (325.0, 265.0),
    (375.0, 390.0),
    (390.0, 315.0),
    (510.0, 200.0),
    (510.0, 390.0),
    (765.0, 280.0),
    (1050.0, 290.0),
)


@dataclass(frozen=True, slots=True)
class PumpSpec:
    """Vakuumerzeuger.

    Zwei Betriebsarten: entweder ein Nennstrom bei einem Bezugsvakuum, oder
    eine Kennlinie aus Stuetzpunkten. Reale Ejektoren liefern bei hohem Vakuum
    deutlich weniger Strom als im Leerlauf; ohne Kennlinie ist der Arbeitspunkt
    nur eine grobe Naeherung, was im Trace vermerkt wird.
    """

    name: str = "Vakuumerzeuger"
    nominal_flow_m3s: float = 0.0
    max_vacuum_pa: float = 85000.0

    #: Stuetzpunkte (vacuum_pa, flow_m3s), aufsteigend nach Vakuum. Leer
    #: bedeutet: lineare Naeherung von nominal_flow bei 0 Pa auf 0 bei
    #: max_vacuum_pa.
    curve_points: tuple[tuple[float, float], ...] = ()


class GripDirection(Enum):
    """Lage der Ansaugflaeche.

    HORIZONTAL Platte greift von oben, das Vakuum traegt die Last unmittelbar.
    VERTICAL   Platte greift seitlich, die Last haengt an der Reibung zwischen
               Sauger und Karton. Der Reibbeiwert ist eine Benutzerangabe und
               steht in keinem Datenblatt.
    """

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"

    @property
    def label(self) -> str:
        return {
            GripDirection.HORIZONTAL: "Von oben (Vakuum traegt direkt)",
            GripDirection.VERTICAL: "Seitlich (Last haengt an der Reibung)",
        }[self]


@dataclass(frozen=True, slots=True)
class VacuumInput:
    """Vollstaendige Eingabe eines Vakuumlaufs."""

    package: PackageSpec
    plate: VacuumPlateSpec
    cup: SuctionCupSpec

    #: 0 bedeutet: automatisch maximal bestuecken.
    requested_cup_count: int = 0
    package_count: int = 1

    #: Muster der Paketanordnung unter der Platte (aus der Palettierung).
    #: Nur noch der Rueckfall: gebraucht wird es, wenn keine Lage uebergeben
    #: wurde oder mehr Pakete gewuenscht sind, als die Lage hergibt.
    pattern_id: str = ""

    #: Die Lage aus der Palettierung, Standflaeche fuer Standflaeche.
    #:
    #: Reicht sie fuer package_count, wird sie unveraendert uebernommen - die
    #: Platte zeigt dann genau die Anordnung, die der Palettentab berechnet
    #: hat. Der Name der Strategie allein genuegt dafuer nicht: aus ihm
    #: entstuende auf der kleineren Plattenflaeche eine andere Anordnung.
    layer_footprints: tuple[Footprint, ...] = ()

    #: Muster, nach dem die Sauger auf der Platte sitzen. Siehe
    #: app/vacuum/cup_patterns.py.
    arrangement_id: str = "grid_spread"

    target_vacuum_pa: float = 60000.0
    ambient_pa: float = STANDARD_AMBIENT_PA
    pump: PumpSpec = field(default_factory=PumpSpec)
    leakage: LeakageSpec = field(default_factory=LeakageSpec)
    restrictor: RestrictorSpec = field(default_factory=RestrictorSpec)

    safety_factor: float = 2.0
    acceleration_ms2: float = 0.0
    gravity_ms2: float = GRAVITY_MS2
    grip: GripDirection = GripDirection.HORIZONTAL

    #: Reibbeiwert Sauger gegen Karton. Nur bei seitlichem Griff wirksam.
    friction_factor: float = 0.5

    #: Ob teilweise aufliegende Sauger als tragend gezaehlt werden. Aus gutem
    #: Grund aus: eine unterbrochene Dichtlippe traegt nicht.
    count_partial_as_sealed: bool = False

    #: Rechnet den Arbeitspunkt statt mit dem Sollvakuum zu rechnen.
    solve_operating_point: bool = True


@dataclass(frozen=True, slots=True)
class FlowBreakdown:
    """Aufteilung des Volumenstroms am Arbeitspunkt."""

    open_cups_m3s: float = 0.0
    partial_cups_m3s: float = 0.0
    workpiece_m3s: float = 0.0
    total_required_m3s: float = 0.0
    available_m3s: float = 0.0

    @property
    def leak_m3s(self) -> float:
        return self.open_cups_m3s + self.partial_cups_m3s

    @property
    def remaining_m3s(self) -> float:
        return self.available_m3s - self.total_required_m3s


@dataclass(frozen=True, slots=True)
class ForceBreakdown:
    """Kraefte am Arbeitspunkt."""

    theoretical_per_cup_n: float = 0.0
    total_holding_n: float = 0.0
    required_n: float = 0.0
    cup_limit_n: float = 0.0
    limited_by_cup_strength: bool = False


@dataclass(frozen=True, slots=True)
class PackageVerdict:
    """Ob die Sauger ueber EINEM Paket genuegen, es zu heben.

    Die Gesamtbilanz der Platte beantwortet das nicht. Sie summiert alle
    Haltekraefte und alle Massen und nimmt damit an, die Platte koenne Kraft
    von einem Paket zum naechsten weiterreichen - das kann sie nicht. Jedes
    Paket haengt an genau den Saugern ueber ihm.

    Gemessen am Vorgabefall mit acht Paketen (Platte 800 x 600, Paket
    400 x 300 x 200, SPB2 30): vier Pakete liegen bei x = -400 und x = 800
    und damit vollstaendig ausserhalb der Platte, bekommen null Sauger und
    haengen an nichts. Die Gesamtbewertung meldete trotzdem "Sicher", denn
    5068 N aus 352 Saugern tragen 40 kg mit Leichtigkeit - nur eben nicht
    dort, wo sie sitzen.
    """

    index: int
    bearing_count: int = 0
    holding_n: float = 0.0
    required_n: float = 0.0
    max_mass_kg: float = 0.0
    status: Status = Status.INSUFFICIENT

    @property
    def holds(self) -> bool:
        """Ob dieses Paket haelt. Grenzwertig zaehlt als haltend - knapp ist
        nicht dasselbe wie zu wenig."""
        return self.status is not Status.INSUFFICIENT


@dataclass(frozen=True, slots=True)
class VacuumResult:
    """Ergebnis eines Vakuumlaufs. Enthaelt nur Daten."""

    meta: CalculationMeta
    plate: VacuumPlateSpec
    cup: SuctionCupSpec
    placements: tuple[SuctionPlacement, ...] = ()
    contacts: tuple[CupContact, ...] = ()
    package_rects: tuple[tuple[float, float, float, float], ...] = ()

    #: Ein Urteil je Paket, in derselben Reihenfolge wie package_rects.
    package_verdicts: tuple[PackageVerdict, ...] = ()

    arrangement_id: str = ""

    #: Mittenabstand benachbarter Sauger. Das Rastermass ist Aussenmass plus
    #: lichtem Mindestabstand - die Anzeige rechnet es nicht nach, sie zeigt
    #: es (Spezifikation 37).
    pitch_x_mm: float = 0.0
    pitch_y_mm: float = 0.0

    total_cup_count: int = 0
    sealed_count: int = 0
    partial_count: int = 0
    open_count: int = 0
    max_cup_count: int = 0

    effective_area_mm2: float = 0.0
    target_vacuum_pa: float = 0.0
    achieved_vacuum_pa: float = 0.0

    flow: FlowBreakdown = field(default_factory=FlowBreakdown)
    force: ForceBreakdown = field(default_factory=ForceBreakdown)

    max_package_mass_kg: float = 0.0
    actual_mass_kg: float = 0.0
    required_cup_count: int = 0
    status: Status = Status.INSUFFICIENT
    warnings: tuple[str, ...] = ()
    trace: FrozenTrace | None = None

    def contact_of(self, placement_index: int) -> CupContact | None:
        for entry in self.contacts:
            if entry.placement_index == placement_index:
                return entry
        return None

    def indices_with(self, contact: ContactClass) -> tuple[int, ...]:
        return tuple(c.placement_index for c in self.contacts if c.contact is contact)

    @property
    def bearing_package_count(self) -> int:
        """Wie viele Pakete ihre Sauger tatsaechlich heben."""
        return sum(1 for verdict in self.package_verdicts if verdict.holds)

    def verdict_of(self, package_index: int) -> PackageVerdict | None:
        if 0 <= package_index < len(self.package_verdicts):
            return self.package_verdicts[package_index]
        return None
