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

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


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
