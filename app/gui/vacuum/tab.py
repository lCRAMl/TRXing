"""Tab 2 - Vakuumplatte.
arrangement_info
Der Tab stellt die Eingaben zu einem VacuumInput zusammen, ruft den
VacuumService und zeigt das Ergebnis. Keine Formel steht hier - weder fuer die
Kraft noch fuer die Leckage, und auch die Bewertung Sicher/Grenzwertig/Nicht
ausreichend kommt fertig aus der Engine (Spezifikation 23).

Das Layout steht in vacuum_tab.ui und wird im Qt Designer bearbeitet:

    vacuum_tab.ui    Anordnung, Gruppen, Beschriftungen, Groessenrichtlinien
       |
       | pyuic6 (tools/build_ui.py)
       v
    Ui_VacuumTab     erzeugt, nicht von Hand aendern
       |
       v
    VacuumTab        Ereignisse, Berechnung, Zustand, Dienst, Ergebnisanzeige

Die Datenblattangaben des gewaehlten Saugers stehen unter dem Auswahlfeld.
Die Annahmen des Rechenmodells fuehrt der Rechenweg weiterhin mit (siehe
CalculationTrace); nachzulesen sind sie unter Hilfe - Rechenwege und Formeln.

Das Muster aus der Palettierung wird uebernommen, sobald dort eines gewaehlt ist
(Spezifikation 18); die Anordnung selbst rechnet die gemeinsame Musterschicht.

Aenderungen an den Paketdaten loesen hier eine neue Berechnung aus, keine
Meldung. Solange der Tab verdeckt ist, wird die Aenderung nur vorgemerkt und
beim Aufschlagen nachgeholt - Rechenzeit fuer Ergebnisse, die niemand ansieht,
waere verschenkt.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSplitter, QVBoxLayout, QWidget
)

from app.domain.results import Status, classify
from app.domain.units import m3s_to_m3h, mbar_to_pa, pa_to_mbar
from app.vacuum.models import RestrictorMode, RestrictorSpec
from app.vacuum.models import GripDirection, LeakageSpec, SharedPlate
from app.vacuum.models import VacuumInput, VacuumPlateSpec, VacuumResult
from qt_controls_pyrs import CompactResultGrid, StaleBanner, compact_combo
from app.gui.debounce import Debouncer
from app.gui.window_state import fit_controls_column, save_splitter, store
from app.tab_registry import TabHost
from app.gui.theme import PALETTE
from app.domain.state import AppStateSnapshot, StateChange
from app.context import AppContext
from app.gui.vacuum.renderer import Vacuum2DView
from app.gui.form_builder import (
    Ganzzahl, Gruppe, Oberflaeche, Schalter, Wahl, Zahl, baue
)

MODULE_ID = "vacuum"

#: Anfangsbreite der Zeichenflaeche in Bildpunkten. Die Bedienspalte bekommt
#: KEINE Zahl mehr: sie ist beim ersten Start genau so breit, wie ihr
#: breitestes Element sie macht - gemessen in _configure_layout().
#:
#: Vorher stand hier ein Paar wie (460, 830). Die 460 waren gemessen, aber am
#: alten Formular: mit zwei umbrechenden Hinweiszeilen nebeneinander und einem
#: Auswahlfeld, das nur die halbe Spalte einnahm. Ohne die Hinweise und mit
#: Zellen, die ihre Zeile ausfuellen, braucht dieselbe Spalte 294 Bildpunkte.
#: Eine feste Zahl waere ab jetzt bei jeder Formularaenderung wieder falsch.
VIEW_WIDTH = 830

#: Abschnitt, unter dem sich der Tab die Aufteilung merkt.
SETTINGS_SECTION = "VacuumTab"

#: Schluessel der gemerkten Teilerstellung.
#:
#: Nicht mehr der alte "splitter": dort liegt auf jedem Rechner, der das
#: Programm schon einmal gestartet hat, die Aufteilung des ALTEN Formulars -
#: 460 bzw. 600 Bildpunkte fuer eine Spalte, die jetzt 294 braucht. Eine
#: gemerkte Breite gewinnt gegen die Vorgabe, die schmale Spalte waere also
#: genau dort nicht zu sehen, wo das Programm benutzt wird. Mit einem neuen
#: Schluessel fangen beide Tabs einmal von vorn an; was der Benutzer danach
#: zieht, wird wieder gemerkt.
SPLITTER_KEY = "splitter_narrow_column"

class EinspaltigesRaster(CompactResultGrid):
    """Ergebniswerte untereinander statt nebeneinander.

    Die Bibliothek setzt zwei Wertepaare nebeneinander, weil das die Hoehe des
    Blocks halbiert. Hier kostet das aber genau das, wofuer die Trennlinien da
    sind: eine Gruppe endet mitten in einer Rasterzeile und die naechste
    laeuft daneben weiter. "Benoetigte wirksame Sauger" stand neben
    "Tatsaechliches Gewicht", obwohl das eine zur ersten und das andere zur
    zweiten Gruppe gehoert. Vier Wertepaare in einer Reihe - zwei Rahmen mit
    je zweien - liest niemand von links nach rechts.

    Eine Unterklasse und kein Argument an CompactResultGrid: die Spaltenzahl
    ist eine Entscheidung DIESER Anwendung ueber DIESE Anzeige, und die
    Bibliothek soll das Aussehen eines Bedienelements bestimmen, nicht den
    Aufbau einer Ergebnisseite.
    """

    COLUMNS = 1


_STATUS_COLORS = {
    Status.SAFE: PALETTE.ok,
    Status.MARGINAL: PALETTE.warning,
    Status.INSUFFICIENT: PALETTE.error,
}


def _ampel(vorhanden: float, noetig: float) -> str:
    """Farbe fuer ein Wertepaar "das haben wir / das brauchen wir".

    Geholt aus classify() und nicht hier entschieden - das ist dieselbe Regel,
    aus der auch die Zeile "Bewertung" entsteht (app/vacuum/calculator.py ruft
    classify(max_mass, actual_mass)). Damit KANN eine Zahl der Bewertung nicht
    widersprechen.

    Genau das war vorher der Fall: "Wirksame Sauger" wurde gruen gefaerbt,
    sobald die Zahl ungleich null war. Bei 104 wirksamen und 109 benoetigten
    stand also gruen neben einem roten "Nicht ausreichend".

    Mitgenommen ist das gelbe Band: classify() nennt es MARGINAL, wenn es
    reicht, aber mit weniger als zehn Prozent Luft. Eine Ja/Nein-Faerbung
    kann das nicht zeigen.

    SAFE bleibt ABSICHTLICH farblos. Farbe heisst hier "sieh hin", und wo
    nichts ist, soll sie nicht hinweisen: gefaerbt waeren sonst im guten Fall
    sieben von elf Zeilen, und wer Gruen gewohnt ist, sieht Rot nicht mehr.
    Dass alles passt, sagt die Zeile "Bewertung" - die ist gruen, und sie ist
    die einzige, die es sein muss.
    """
    status = classify(vorhanden, noetig)
    return "" if status is Status.SAFE else _STATUS_COLORS.get(status, "")


#: Die Bedienspalte als Beschreibung.
#:
#: Wertebereiche, Einheiten und Erklaerungen stehen hier, weil sie Fachwissen
#: sind und keine Gestaltung. Frueher lag die Beschriftung in der XML-Datei und
#: die Einheit im Quelltext - wer die Einheit aenderte, musste beides suchen.
BEDIENSPALTE = [
    Gruppe("Platte und Sauger", [
        [Wahl("cup_box", "Sauger-Typ")],
        # Laenge und Breite gehoeren in eine Zeile, Randabstand und
        # Rastermass in die naechste: beides sind Paare, die man zusammen
        # einstellt und zusammen liest.
        [Zahl("plate_length", "Laenge", "mm",
              dict(min=10.0, max=3000.0, stellen=0, schritt=10.0)),
         Zahl("plate_width", "Breite", "mm",
              dict(min=10.0, max=3000.0, stellen=0, schritt=10.0))],
        # Das Rastermass ist der MITTENabstand, nicht die Luecke dazwischen.
        # Bis zum 2026-11-01 stand hier der lichte Abstand - dieselbe Groesse
        # in anderer Schreibweise und damit ein zweites Feld fuer eine Sache.
        # Schmalz kennzeichnet seine Bauformen ueber den Mittenabstand
        # (20T/30T/45T), also tut es das Formular auch. Der lichte Abstand
        # steht jetzt als ERGEBNIS rechts in der Ergebnisanzeige.
        [Zahl("edge_margin", "Randabstand", "mm",
              dict(min=0.0, max=500.0, stellen=0, schritt=5.0)),
         Zahl("raster_pitch", "Rastermass", "mm", dict(
            min=1.0, max=500.0, stellen=1, schritt=1.0,
            hinweis="Mittenabstand zweier Sauger, von Mitte zu Mitte.\n"
                    "Kleiner als das Saugeraussenmass ist erlaubt - die\n"
                    "Sauger ueberlappen sich dann, und es gibt eine Warnung."))],
        [Wahl("raster_box", "Bauform des Rasters")],
        # Der Hinweis ist der Vorbelegungstext des Tooltips. Er TRAEGT NICHT -
        # die Gegenprobe ohne ihn blieb gruen: compact_combo() wuerde dann den
        # sichtbaren Eintrag nachfuehren, haengt dafuer aber schon beim Bau am
        # Signal, waehrend _on_arrangement_changed() erst in
        # _connect() dazukommt und als Letzter schreibt. Der Text steht
        # trotzdem da, aus zwei Gruenden: bis zur ersten Auswahl waere der
        # Tooltip sonst leer, und mit ihm schliesst compact_combo() das
        # Nachfuehren gar nicht erst an - die Beschreibung haengt dann nicht
        # an der Reihenfolge zweier Verbindungen.
        [Wahl("arrangement_box", "Saugermuster",
              hinweis="Das gewaehlte Muster wird hier beschrieben.")],
        # "automatisch" und nicht "automatisch (maximal)": das Feld haelt
        # Platz fuer seinen laengsten Text frei, und die Klammer kostete
        # 232 statt 162 Bildpunkte.
        [Ganzzahl("cup_count", "Saugeranzahl", "Stueck", dict(
            min=0, max=20000, wert=0, null_text="automatisch"))],
    ], name="plate_box", oben=True),

    Gruppe("Pakete", [
        [Ganzzahl("package_count", "Anzahl Pakete", "Stueck",
                  dict(min=1, max=200, wert=1))],
        [Schalter("use_pallet_pattern", "Muster aus der Palettierung uebernehmen",
                  angehakt=True,
                  hinweis="Ordnet die Pakete nach dem in der Palettierung "
                          "gewaehlten Muster an.\n"
                          "Aus: gleichmaessiges Raster.")],
    ], name="package_box", oben=True),

    Gruppe("Vakuum und Sicherheit", [
        # Der Arbeitspunkt des Erzeugers: ein Paar aus Saugvermoegen und
        # Endvakuum. Das Auswahlfeld setzt beide Zahlen, die Felder bleiben
        # frei - wer eigene Werte tippt, bekommt "frei eingestellt".
        [Wahl("pump_box", "Vakuumerzeuger", zeichen=18,
              hinweis="Arbeitspunkte der Schmalz-Seitenkanalgeblaese bei 50 Hz.\n"
                      "Saugvermoegen und Endvakuum gehoeren je Geraet zusammen:\n"
                      "510 m3/h gibt es bei 200 UND bei 390 mbar.")],
        [Zahl("flow", "Saugvermoegen", "m3/h", dict(
            min=0.0, max=2000.0, stellen=2, schritt=10.0,
            hinweis="Saugvermoegen des Erzeugers bei geringem Unterdruck.")),
         Zahl("end_vacuum", "Endvakuum", "mbar", dict(
            min=10.0, max=1000.0, stellen=0, schritt=5.0,
            hinweis="Hoechstes Vakuum, das der Erzeuger erreicht.\n"
                    "Es deckelt das Sollvakuum: mehr geht nicht."))],
        [Zahl("vacuum", "Sollvakuum", "mbar", dict(
            min=10.0, max=1000.0, stellen=0, schritt=25.0,
            hinweis="Unterdruck, mit dem gerechnet werden soll. Die Wahl eines\n"
                    "Arbeitspunkts zieht ihn auf dessen Endvakuum nach - mehr\n"
                    "kann man von dem Geraet nicht verlangen."))],
        [Wahl("restrictor_box", "Absperrung je Sauger",
              hinweis="Absperrung je Saugerposition. Ohne Begrenzung reissen unbelegte Sauger\n"
                          "das Vakuum der ganzen Platte ein. Keine Datenblattangabe.")],
        [Wahl("leakage_box", "Kartonpermeabilitaet")],
        [Zahl("permeability", "Permeabilitaet", "",
              dict(min=0.0, max=100.0, stellen=3, schritt=0.05)),
         Zahl("safety", "Sicherheit", "", dict(
            min=1.0, max=20.0, stellen=1, schritt=0.5,
            hinweis="Die Datenblattkraefte enthalten ausdruecklich KEINEN "
                    "Sicherheitsfaktor.\nEr wird hier gesondert angesetzt."))],
        # Ansaugrichtung und Reibbeiwert gehoeren zusammen: der Beiwert wirkt
        # nur beim seitlichen Griff. Nebeneinander ist das ablesbar.
        [Wahl("grip_box", "Ansaugrichtung")],
        [Zahl("acceleration", "Beschleunigung", "m/s2", dict(
            min=0.0, max=200.0, stellen=2, schritt=0.5,
            hinweis="Zusaetzliche Beschleunigung der Handhabung. "
                    "0 ergibt die rein statische Rechnung.")),
         Zahl("friction", "Reibbeiwert", "", dict(
            min=0.01, max=2.0, stellen=2, schritt=0.05,
            hinweis="Reibbeiwert Sauger gegen Karton. Benutzerangabe, "
                    "keine Datenblattgroesse."))],
        [Schalter("partial_counts", "Teilweise aufliegende Sauger als tragend zaehlen",
                  hinweis="Aus (empfohlen): ein unterbrochener Dichtlippenring traegt nicht.\n"
                          "Ein: optimistische Annahme, nur bei sehr nachgiebiger Dichtlippe vertretbar.")],
        [Schalter("solve_point", "Arbeitspunkt loesen statt Sollvakuum annehmen",
                  angehakt=True, hinweis="Ein (empfohlen): rechnet das Vakuum, das sich gegen die Leckage tatsaechlich einstellt.\n"
                          "Aus: rechnet mit dem eingestellten Sollvakuum und warnt nur bei Ueberlast.")],
    ], name="physics_box", oben=True),

#: Keine Knopfzeile mehr.
#:
#: Gerechnet wird nach jeder Eingabe von selbst, entprellt. Ein Knopf
#: "Berechnen" war damit ein zweiter Weg zum gleichen Ergebnis - und einer,
#: der beim Hinsehen das Gegenteil behauptet: wer ihn sieht, haelt die Anzeige
#: fuer veraltet, bis er geklickt hat. Der Abbruch steht in der Statusleiste,
#: neben dem Fortschritt, den er abbricht (siehe app/gui/notifications.py).
]

def _raster_rows(cup, raster) -> tuple[tuple[str, str, str], ...]:
    """Was das Raster kostet, als Zeilen der Ergebnisanzeige.

    Drei Angaben: das Rastermass mit dem Saugeraussenmass dahinter, der
    daraus folgende lichte Abstand und die Hoechstzahl. Der lichte Abstand
    ist ein ERGEBNIS und keine Eingabe - wird er negativ, ueberlappen sich
    die Sauger, und dann steht dort die Ueberlappung statt einer Luecke.

    Bis zum 2026-11-01 stand das als Hinweiszeile unter der Saugeranzahl.
    Dort kostete es Breite in der Bedienspalte, und zwar die teuerste: ein
    umbrechender Hinweis verlangt 240 Bildpunkte, zweimal nebeneinander hielt
    er die Spalte bei 386. Im Ergebnisraster rechts kostet er keine.

    Gerechnet wird nichts: die Zahlen kommen fertig aus der Engine
    (Spezifikation 37), hier werden sie nur benannt. Je Zeile
    (Name, Wert, Farbe) - die leere Farbe heisst "wie der uebrige Text".
    """
    if raster.clearance_mm < 0.0:
        luft = ("Ueberlappung " + format(-raster.clearance_mm, ".1f") + " mm",
                PALETTE.warning)
    else:
        luft = (format(raster.clearance_mm, ".1f") + " mm", "")
    return (
        ("pitch", format(raster.pitch_mm, "g") + " mm  (Aussenmass "
                  + format(cup.outer_diameter_mm, "g") + " mm)", ""),
        ("clearance", luft[0], luft[1]),
        ("cup_max", str(raster.max_cup_count) + " Stueck", ""),
    )


#: Kennzahlen der beiden Zustaende im Bauform-Auswahlfeld.
#:
#: Sie stehen an derselben Stelle wie ein Rastermass in mm, sind aber keines.
#: Negativ, weil ein Rastermass nie negativ wird - damit lassen sie sich mit
#: keiner echten Bauform verwechseln.
RASTER_AUTOMATISCH = -1.0
RASTER_FREI = -2.0

#: Kennzahl des Eintrags "frei eingestellt" im Erzeugerfeld.
#:
#: Die uebrigen Eintraege tragen ihren Platz in SCHMALZ_OPERATING_POINTS als
#: Kennzahl. Ein Paar liesse sich nicht als currentData() vergleichen, ohne
#: zwei Gleitkommazahlen auf Gleichheit zu pruefen - der Platz ist eindeutig.
PUMP_FREI = -1


#: Die Zeilen der beiden Ergebnisanzeigen. None ist eine Trennlinie.
ERGEBNISZEILEN = [
    ("status", "Bewertung"),
    ("max_mass", "Max. Paketgewicht"),
    ("actual_mass", "Tatsaechliches Gewicht"),
    ("needed_cups", "Benoetigte wirksame Sauger"),
    None,
    ("arrangement", "Saugermuster"),
    # Die drei Rasterzeilen fuellt NICHT die Rechnung, sondern
    # _update_cup_limit() bei jeder Eingabe - sie sind Geometrie der Platte
    # und stehen deshalb schon da, bevor gerechnet wurde.
    ("pitch", "Rastermass"),
    ("clearance", "Lichter Abstand"),
    ("cup_max", "Sauger hoechstens"),
    ("cups_total", "Sauger gesamt"),
    ("cups_sealed", "Wirksame Sauger"),
    ("cups_partial", "Teilweise aufliegend"),
    ("cups_open", "Offene Sauger"),
    ("area", "Effektive Saugflaeche"),
    None,
    ("packages", "Pakete, davon tragend"),
]

STROMZEILEN = [
    ("vacuum", "Vakuum (Soll / erreicht)"),
    ("force", "Haltekraft"),
    ("per_cup", "davon je Sauger"),
    None,
    ("flow_required", "Volumenstrom benoetigt"),
    ("flow_available", "Volumenstrom verfuegbar"),
    ("flow_open", "davon offene Sauger"),
    ("flow_workpiece", "davon Karton"),
    ("flow_left", "Verbleibend"),
    None,
    ("safety", "Sicherheitsfaktor"),
]


class VacuumTab(TabHost):
    """Vakuumplatte mit Draufsicht und Ergebnisanzeige."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._service = context.vacuum
        self._defaults = self._service.defaults()
        self._result: VacuumResult | None = None
        self._result_revision = -1
        self._needs_recalculation = False
        #: Die drei Rasterzeilen der Ergebnisanzeige, zuletzt gesetzt von
        #: _update_cup_limit(). Leer, bis ein Sauger gewaehlt ist.
        self._raster_values: tuple[tuple[str, str, str], ...] = ()
        #: Die zuletzt abgeschickte Anfrage. Sie geht mit dem Ergebnis an den
        #: Vakuumverlauf - ohne sie fehlten ihm Sauger, Leckage und Erzeuger.
        self._request: VacuumInput | None = None
        self._debouncer = Debouncer(self.calculate, context.debounce_ms, self)

        # Zusammensetzung statt Vererbung: die aus der Layoutdatei erzeugten
        # Namen liegen unter self.ui und koennen weder mit denen von QWidget
        # noch mit eigenen kollidieren.
        # Die Namen kommen aus BEDIENSPALTE statt aus einer erzeugten Datei.
        self.ui = Oberflaeche()
        self._build_layout()

        self._configure_layout()
        self._build_result_rows()
        self._connect()

        self._connect_service()
        self._fill_catalogs()
        self._apply_defaults()
        self._update_cup_limit()

    # Aufbau -------------------------------------------------------------------

    def _build_layout(self) -> None:
        """Setzt das Fenster zusammen: Band, Teiler, Zeichenflaeche.

        Der Formularteil kommt aus BEDIENSPALTE; hier steht die Umgebung.
        """
        self.ui.root = QVBoxLayout(self)
        self.ui.root.setContentsMargins(6, 6, 6, 6)
        self.ui.root.setSpacing(4)

        self.ui.banner = StaleBanner()
        self.ui.root.addWidget(self.ui.banner)

        self.ui.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.ui.root.addWidget(self.ui.splitter)

        self.ui.controls, self.ui = baue(BEDIENSPALTE, self.ui)
        self.ui.controls_scroll = QScrollArea()
        self.ui.controls_scroll.setWidgetResizable(True)
        self.ui.controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.ui.controls_scroll.setWidget(self.ui.controls)
        self.ui.splitter.addWidget(self.ui.controls_scroll)

        self.ui.view_panel = QWidget()
        self.ui.view_layout = QVBoxLayout(self.ui.view_panel)
        self.ui.view_layout.setContentsMargins(0, 0, 0, 0)
        self.ui.view_layout.setSpacing(4)

        self.ui.view = Vacuum2DView()
        self.ui.view_layout.addWidget(self.ui.view, 1)

        # Die beiden Ergebnisraster nebeneinander unter der Zeichnung, jedes
        # aber EINSPALTIG: Beschriftung links, Wert rechts, eine Zeile je Wert.
        #
        # Zweispaltig passte zwar mehr auf weniger Hoehe, kostete aber genau
        # das, wofuer die Trennlinien da sind: eine Gruppe endete mitten in
        # einer Rasterzeile und die naechste lief daneben weiter. "Benoetigte
        # wirksame Sauger" stand neben "Tatsaechliches Gewicht", obwohl das
        # eine zur ersten und das andere zur zweiten Gruppe gehoert. Vier
        # Wertepaare in einer Reihe liest niemand von links nach rechts.
        self.ui.result_row = QHBoxLayout()
        self.ui.result_row.setSpacing(6)
        self.ui.results = EinspaltigesRaster("Ergebnis")
        self.ui.flow_results = EinspaltigesRaster("Vakuum, Kraft und Volumenstrom")
        self.ui.result_row.addWidget(self.ui.results)
        self.ui.result_row.addWidget(self.ui.flow_results)
        self.ui.view_layout.addLayout(self.ui.result_row)

        self.ui.splitter.addWidget(self.ui.view_panel)

    def _configure_layout(self) -> None:
        """Was der Designer nicht speichern kann."""
        # Die Zeichenflaeche bekommt den Platz, den das Fenster ueber den
        # Hinweisstreifen hinaus hat.
        self.ui.root.setStretch(1, 1)
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)

        fit_controls_column(
            self.ui.splitter, self.ui.controls_scroll, self.ui.controls,
            VIEW_WIDTH, SETTINGS_SECTION, key=SPLITTER_KEY,
        )

        # Lange Eintraege duerfen die Bedienspalte nicht auseinanderziehen; die
        # Groessenrichtlinie dafuer steht in der .ui-Datei. compact_combo
        # ergaenzt den Tooltip mit dem vollstaendigen Text - ausser dort, wo im
        # Designer bereits eine Erklaerung hinterlegt ist.
        for combo in (self.ui.cup_box, self.ui.arrangement_box, self.ui.restrictor_box,
                      self.ui.leakage_box, self.ui.grip_box):
            compact_combo(combo)

    def _build_result_rows(self) -> None:
        """Die Zeilen beider Ergebnisanzeigen, aus den Listen oben."""
        for raster, zeilen in ((self.ui.results, ERGEBNISZEILEN),
                               (self.ui.flow_results, STROMZEILEN)):
            for eintrag in zeilen:
                if eintrag is None:
                    raster.add_separator()
                else:
                    raster.add_row(*eintrag)

    def _connect(self) -> None:

        self.ui.cup_box.currentIndexChanged.connect(self._on_cup_changed)
        self.ui.arrangement_box.currentIndexChanged.connect(self._on_arrangement_changed)
        self.ui.leakage_box.currentIndexChanged.connect(self._on_leakage_changed)
        self.ui.grip_box.currentIndexChanged.connect(self._on_grip_changed)
        self.ui.restrictor_box.currentIndexChanged.connect(lambda *_: self._debouncer.trigger())

        # Die Plattenmasse aendern, wie viele Sauger ueberhaupt passen - sie
        # brauchen deshalb einen eigenen Weg, nicht nur die Neuberechnung.
        for field in (self.ui.plate_length, self.ui.plate_width,
                      self.ui.edge_margin, self.ui.raster_pitch):
            field.value_changed.connect(self._on_plate_changed)

        self.ui.raster_box.currentIndexChanged.connect(self._on_raster_box_changed)
        self.ui.pump_box.currentIndexChanged.connect(self._on_pump_box_changed)

        # Die beiden Kennwerte des Erzeugers fuehren das Auswahlfeld nach -
        # sie brauchen deshalb einen eigenen Weg, nicht nur die Neuberechnung.
        for field in (self.ui.flow, self.ui.end_vacuum):
            field.value_changed.connect(self._on_pump_values_changed)

        for field in (self.ui.cup_count, self.ui.package_count, self.ui.vacuum,
                      self.ui.permeability, self.ui.safety, self.ui.acceleration, self.ui.friction):
            field.value_changed.connect(lambda *_: self._debouncer.trigger())

        for box in (self.ui.use_pallet_pattern, self.ui.partial_counts, self.ui.solve_point):
            box.toggled.connect(lambda *_: self._debouncer.trigger())

    def _connect_service(self) -> None:
        self._service.started.connect(self._on_started)
        self._service.result_ready.connect(self._on_result)
        self._service.failed.connect(self._on_failed)

        # Eine neue oder andere Lage im Palettentab aendert, was unter der
        # Platte liegt - und damit das Ergebnis hier. Der Weg ueber den
        # Palettenservice haelt die beiden Tabs voneinander fern: sie kennen
        # denselben Service, aber nicht einander.
        self._context.pallets.layer_published.connect(self._on_layer_published)

    # Vorgaben -----------------------------------------------------------------

    def _fill_catalogs(self) -> None:
        self.ui.cup_box.blockSignals(True)
        self.ui.cup_box.clear()
        for cup in self._service.available_cups():
            self.ui.cup_box.addItem(cup.name + "  (" + cup.manufacturer + ")", cup.id)
        self.ui.cup_box.blockSignals(False)

        self.ui.arrangement_box.blockSignals(True)
        self.ui.arrangement_box.clear()
        for strategy_id, label, _description in self._service.available_arrangements():
            self.ui.arrangement_box.addItem(label, strategy_id)
        self.ui.arrangement_box.blockSignals(False)

        self.ui.raster_box.blockSignals(True)
        self.ui.raster_box.clear()
        self.ui.raster_box.addItem("automatisch (aus dem Sauger)", RASTER_AUTOMATISCH)
        for code, pitch_mm in self._service.available_rasters():
            self.ui.raster_box.addItem(
                code + "  -  " + format(pitch_mm, "g") + " mm", pitch_mm)
        self.ui.raster_box.addItem("frei eingestellt", RASTER_FREI)
        self.ui.raster_box.blockSignals(False)

        self.ui.pump_box.blockSignals(True)
        self.ui.pump_box.clear()
        for nummer, (strom_m3h, vakuum_mbar) in enumerate(
                self._service.available_operating_points()):
            self.ui.pump_box.addItem(
                format(strom_m3h, "g") + " m3/h bei " + format(vakuum_mbar, "g") + " mbar",
                nummer,
            )
        self.ui.pump_box.addItem("frei eingestellt", PUMP_FREI)
        self.ui.pump_box.blockSignals(False)

        self.ui.restrictor_box.blockSignals(True)
        self.ui.restrictor_box.clear()
        for mode in RestrictorMode:
            self.ui.restrictor_box.addItem(mode.label, mode.value)
        self.ui.restrictor_box.blockSignals(False)

        self.ui.grip_box.blockSignals(True)
        self.ui.grip_box.clear()
        for grip in GripDirection:
            self.ui.grip_box.addItem(grip.label, grip.value)
        self.ui.grip_box.blockSignals(False)

        self.ui.leakage_box.blockSignals(True)
        self.ui.leakage_box.clear()
        for preset in self._defaults.leakage_presets:
            self.ui.leakage_box.addItem(preset.name, preset.id)
        self.ui.leakage_box.blockSignals(False)

    def _apply_defaults(self) -> None:
        defaults = self._defaults
        index = self.ui.cup_box.findData(defaults.default_cup_id)
        if index >= 0:
            self.ui.cup_box.setCurrentIndex(index)

        self.ui.plate_length.set_value(defaults.plate.length_mm)
        self.ui.plate_width.set_value(defaults.plate.width_mm)
        self.ui.edge_margin.set_value(defaults.plate.edge_margin_mm)
        self.ui.vacuum.set_value(pa_to_mbar(defaults.target_vacuum_pa))
        self.ui.flow.set_value(m3s_to_m3h(defaults.pump.nominal_flow_m3s))
        self.ui.end_vacuum.set_value(pa_to_mbar(defaults.pump.max_vacuum_pa))
        self._show_pump_box()
        self.ui.safety.set_value(defaults.safety_factor)
        self.ui.acceleration.set_value(defaults.acceleration_ms2)
        self.ui.friction.set_value(defaults.friction_factor)
        self.ui.package_count.set_value(defaults.package_count)
        self.ui.partial_counts.setChecked(defaults.count_partial_as_sealed)
        self.ui.solve_point.setChecked(defaults.solve_operating_point)

        arrangement_index = self.ui.arrangement_box.findData(defaults.arrangement_id)
        if arrangement_index >= 0:
            self.ui.arrangement_box.setCurrentIndex(arrangement_index)

        mode_index = self.ui.restrictor_box.findData(defaults.restrictor.mode.value)
        if mode_index >= 0:
            self.ui.restrictor_box.setCurrentIndex(mode_index)
        grip_index = self.ui.grip_box.findData(defaults.grip.value)
        if grip_index >= 0:
            self.ui.grip_box.setCurrentIndex(grip_index)

        self._on_cup_changed()

        # NACH _on_cup_changed(), denn das stellt auf "automatisch". Gibt die
        # Konfiguration ein Rastermass vor, soll ihres gelten.
        if defaults.plate.raster_pitch_mm > 0.0:
            self.ui.raster_pitch.set_value(defaults.plate.raster_pitch_mm)

        self._on_arrangement_changed()
        self._on_leakage_changed()
        self._on_grip_changed()

    # Eingaben -----------------------------------------------------------------

    def _current_cup(self):
        return self._context.settings.get_suction_cup(self.ui.cup_box.currentData())

    def _current_plate(self) -> VacuumPlateSpec:
        return VacuumPlateSpec(
            length_mm=self.ui.plate_length.value(),
            width_mm=self.ui.plate_width.value(),
            thickness_mm=self._defaults.plate.thickness_mm,
            edge_margin_mm=self.ui.edge_margin.value(),
            # Der lichte Abstand steht nicht mehr im Formular. Er bleibt als
            # Grundlage von "automatisch" erhalten und kommt aus der
            # Konfiguration; eingestellt wird das Rastermass selbst.
            min_spacing_mm=self._defaults.plate.min_spacing_mm,
            raster_pitch_mm=self.ui.raster_pitch.value(),
        )

    def _current_leakage(self) -> LeakageSpec:
        preset_id = self.ui.leakage_box.currentData()
        preset = next((p for p in self._defaults.leakage_presets if p.id == preset_id), None)
        if preset is None:
            return self._defaults.leakage
        return replace(preset.spec, permeability_value=self.ui.permeability.value())

    def _on_cup_changed(self, *_args) -> None:
        cup = self._current_cup()
        if cup is None:
            return
        self._context.state.set_suction_cup_id(cup.id)
        self._select_automatic_raster()
        self._update_cup_limit()
        self._debouncer.trigger()

    def _select_automatic_raster(self) -> None:
        """Stellt das Rastermass auf den Wert des gewaehlten Saugers.

        Bei JEDEM Saugerwechsel - so ausdruecklich gewuenscht. Der Preis steht
        hier, damit er nicht vergessen wird: wer zwei Sauger bei festem 30T
        vergleichen will, muss die Bauform nach jedem Wechsel erneut waehlen.
        """
        cup = self._current_cup()
        if cup is None:
            return
        mass = self._service.raster_overview(
            cup, self._current_plate(), self._current_arrangement()
        ).automatic_pitch_mm
        if mass <= 0.0:
            return
        self.ui.raster_pitch.blockSignals(True)
        self.ui.raster_pitch.set_value(mass)
        self.ui.raster_pitch.blockSignals(False)

    def _on_raster_box_changed(self, *_args) -> None:
        """Eine Bauform gewaehlt: das Rastermass nachziehen.

        "frei eingestellt" ist kein Mass, sondern die Anzeige dafuer, dass die
        Zahl von Hand kommt - da bleibt das Feld unberuehrt.
        """
        mass = self.ui.raster_box.currentData()
        if mass is None or mass == RASTER_FREI:
            return
        if mass == RASTER_AUTOMATISCH:
            self._select_automatic_raster()
        else:
            self.ui.raster_pitch.blockSignals(True)
            self.ui.raster_pitch.set_value(mass)
            self.ui.raster_pitch.blockSignals(False)
        self._on_plate_changed()

    def _show_raster_box(self, raster) -> None:
        """Stellt im Auswahlfeld die Bauform ein, die zum Mass gehoert.

        Verglichen werden die MASSE, nicht ein gemerkter Zustand. Damit stimmt
        die Anzeige auch, wenn der Wert von woanders kommt - aus der
        Vorbelegung, vom Saugerwechsel oder aus der Konfiguration. Und wenn
        ein von Hand getipptes Mass einer Bauform entspricht, heisst es auch
        so: 30 mm SIND 30T, egal wie sie zustande kamen.
        """
        if abs(raster.pitch_mm - raster.automatic_pitch_mm) < 0.05:
            kennung = RASTER_AUTOMATISCH
        elif self.ui.raster_box.findData(raster.pitch_mm) >= 0:
            kennung = raster.pitch_mm
        else:
            kennung = RASTER_FREI

        index = self.ui.raster_box.findData(kennung)
        if index < 0:
            return
        self.ui.raster_box.blockSignals(True)
        self.ui.raster_box.setCurrentIndex(index)
        self.ui.raster_box.blockSignals(False)

    def _on_pump_box_changed(self, *_args) -> None:
        """Ein Arbeitspunkt gewaehlt: beide Kennwerte nachziehen.

        Das Sollvakuum geht mit. Kein Geraet der Liste schafft mehr als
        445 mbar; bliebe das Sollvakuum auf seinen 600 stehen, stuende bei
        JEDER Rechnung die Warnung "Sollvakuum wird nicht erreicht" im
        Protokoll - und eine Warnung, die immer kommt, liest niemand mehr.
        Das Feld bleibt frei: wer mit weniger rechnen will, stellt weniger ein.

        "frei eingestellt" ist kein Arbeitspunkt, sondern die Anzeige dafuer,
        dass die Zahlen von Hand kommen - da bleiben die Felder unberuehrt.
        """
        nummer = self.ui.pump_box.currentData()
        if nummer is None or nummer == PUMP_FREI:
            return
        punkte = self._service.available_operating_points()
        if not 0 <= nummer < len(punkte):
            return
        strom_m3h, vakuum_mbar = punkte[nummer]
        for feld, wert in ((self.ui.flow, strom_m3h),
                           (self.ui.end_vacuum, vakuum_mbar),
                           (self.ui.vacuum, vakuum_mbar)):
            feld.blockSignals(True)
            feld.set_value(wert)
            feld.blockSignals(False)
        self._debouncer.trigger()

    def _on_pump_values_changed(self, *_args) -> None:
        self._show_pump_box()
        self._debouncer.trigger()

    def _show_pump_box(self) -> None:
        """Stellt im Auswahlfeld den Arbeitspunkt ein, der zu den Zahlen passt.

        Verglichen werden die ZAHLEN und kein gemerkter Zustand - wie beim
        Rastermass. Damit stimmt die Anzeige auch, wenn die Werte aus der
        Konfiguration kommen, und von Hand getippte 510 bei 390 heissen auch
        so, egal wie sie zustande kamen.

        Verglichen wird auf die halbe Anzeigestelle genau: das Stromfeld
        fuehrt zwei Nachkommastellen, 510 m3/h liegen dort als 510,00, und
        ein Arbeitspunkt aus einer Konfiguration mit 0,14166667 m3/s ergibt
        510,000012. Ein exakter Vergleich waere immer ungleich.
        """
        strom = self.ui.flow.value()
        vakuum = self.ui.end_vacuum.value()
        strom_genau = 10.0 ** -self.ui.flow.spin.decimals() / 2.0
        vakuum_genau = 10.0 ** -self.ui.end_vacuum.spin.decimals() / 2.0

        kennung = PUMP_FREI
        for nummer, (strom_m3h, vakuum_mbar) in enumerate(
                self._service.available_operating_points()):
            if abs(strom - strom_m3h) <= strom_genau and abs(vakuum - vakuum_mbar) <= vakuum_genau:
                kennung = nummer
                break

        index = self.ui.pump_box.findData(kennung)
        if index < 0:
            return
        self.ui.pump_box.blockSignals(True)
        self.ui.pump_box.setCurrentIndex(index)
        self.ui.pump_box.blockSignals(False)

    def _on_plate_changed(self, *_args) -> None:
        self._context.state.notify_plate_changed()
        self._update_cup_limit()
        self._debouncer.trigger()

    def _current_arrangement(self) -> str:
        return self.ui.arrangement_box.currentData() or "grid_spread"

    def _on_arrangement_changed(self, *_args) -> None:
        strategy_id = self._current_arrangement()
        for known_id, _label, description in self._service.available_arrangements():
            if known_id == strategy_id:
                self.ui.arrangement_box.setToolTip(description)
                break
        self._update_cup_limit()
        self._debouncer.trigger()

    def _on_leakage_changed(self, *_args) -> None:
        preset_id = self.ui.leakage_box.currentData()
        preset = next((p for p in self._defaults.leakage_presets if p.id == preset_id), None)
        if preset is None:
            return
        self.ui.permeability.set_value(preset.spec.permeability_value)
        self.ui.permeability.setEnabled(preset.spec.model.value != "none")
        self.ui.permeability.clear_message()
        if preset.spec.unit_label:
            self.ui.permeability.set_warning(
                "Einheit: " + preset.spec.unit_label + " (Benutzerangabe, kein Messwert)"
            )
        self._debouncer.trigger()

    def _on_grip_changed(self, *_args) -> None:
        vertical = self.ui.grip_box.currentData() == GripDirection.VERTICAL.value
        self.ui.friction.setEnabled(vertical)
        self._debouncer.trigger()

    def _update_cup_limit(self) -> None:
        """Bauform nachfuehren und zeigen, was das Raster kostet.

        Ein einziger Dienstaufruf fuer alles. Frueher standen hier zwei -
        einer fuer die Hoechstzahl, einer fuer den Vergleich mit Abstand null -
        und beide liefen bei jedem Tastendruck in einem Plattenmass.
        """
        cup = self._current_cup()
        if cup is None:
            return

        raster = self._service.raster_overview(
            cup, self._current_plate(), self._current_arrangement()
        )
        # Untergrenze des Eingabefelds. Sie haengt am Sauger, deshalb hier und
        # nicht in der Formularbeschreibung. Nur setzen, wenn sie sich wirklich
        # aendert: setRange() zieht einen zu kleinen Wert nach und loest dabei
        # value_changed aus - das liefe sonst bei jedem Durchlauf erneut.
        #
        # Verglichen wird mit der AUFLOESUNG des Feldes und nicht auf die
        # Stelle genau. Das Feld fuehrt eine Nachkommastelle und speichert
        # eine Grenze von 5,65 mm als 5,70; ein exakter Vergleich waere
        # dadurch immer ungleich, und setRange() liefe bei jedem Durchlauf.
        # Die 0,05 mm mehr sind unschaedlich - sie machen die Grenze um eine
        # halbe Anzeigestelle strenger, nicht lockerer.
        aufloesung = 10.0 ** -self.ui.raster_pitch.spin.decimals() / 2.0
        if raster.min_pitch_mm > 0.0 and \
                abs(self.ui.raster_pitch.spin.minimum() - raster.min_pitch_mm) > aufloesung:
            self.ui.raster_pitch.configure(minimum=raster.min_pitch_mm)

        self._show_raster_box(raster)
        self.ui.cup_count.set_maximum(max(0, raster.max_cup_count))
        self._raster_values = _raster_rows(cup, raster)
        self._show_raster_values()

    def _show_raster_values(self) -> None:
        """Schreibt die gemerkten Rasterwerte in die Ergebnisanzeige.

        Gemerkt, weil clear_values() beim Fehlschlag der Rechnung ALLE Zeilen
        leert - auch diese drei, die mit der Rechnung nichts zu tun haben. Sie
        kaemen sonst erst beim naechsten Tastendruck in einem Plattenmass
        wieder, und bis dahin stuende dort nichts, obwohl das Raster feststeht.
        """
        for name, wert, farbe in self._raster_values:
            self.ui.results.set_value(name, wert, farbe)

    # Berechnung ---------------------------------------------------------------

    def calculate(self) -> None:
        self._debouncer.cancel()
        snapshot = self._context.state.snapshot()
        package = snapshot.package
        cup = self._current_cup()

        if package is None:
            self.ui.banner.show_message(
                "Es sind noch keine gueltigen Paketdaten hinterlegt - "
                "siehe Tab 'Palettierung', Paketdaten ganz oben."
            )
            self._service.invalidate()
            return
        if cup is None:
            self.ui.banner.show_message("Kein Saugertyp verfuegbar - Konfiguration pruefen.")
            return

        pattern_id = ""
        layer_footprints: tuple = ()
        adopt = self.ui.use_pallet_pattern.isChecked()

        if adopt and snapshot.pattern_id:
            pattern = self._context.settings.get_pattern(snapshot.pattern_id)
            if pattern is not None:
                pattern_id = pattern.strategy

        # Die berechnete Lage selbst, nicht nur der Name ihrer Strategie. Nur
        # damit sieht die Platte genauso aus wie die Palette.
        layer = self._context.pallets.published_layer() if adopt else None
        count = self.ui.package_count.value()
        if layer is not None and layer.footprints:
            layer_footprints = layer.footprints

        request = VacuumInput(
            package=package,
            plate=self._current_plate(),
            cup=cup,
            requested_cup_count=self.ui.cup_count.value(),
            package_count=count,
            pattern_id=pattern_id,
            layer_footprints=layer_footprints,
            arrangement_id=self._current_arrangement(),
            target_vacuum_pa=mbar_to_pa(self.ui.vacuum.value()),
            ambient_pa=self._defaults.ambient_pa,
            pump=replace(
                self._defaults.pump,
                nominal_flow_m3s=self.ui.flow.value() / 3600.0,
                max_vacuum_pa=mbar_to_pa(self.ui.end_vacuum.value()),
            ),
            leakage=self._current_leakage(),
            restrictor=RestrictorSpec(
                mode=RestrictorMode(self.ui.restrictor_box.currentData()),
                diameter_mm=self._defaults.restrictor.diameter_mm,
                check_valve_leak_ratio=self._defaults.restrictor.check_valve_leak_ratio,
                discharge_coefficient_factor=self._defaults.restrictor.discharge_coefficient_factor,
            ),
            safety_factor=self.ui.safety.value(),
            acceleration_ms2=self.ui.acceleration.value(),
            grip=GripDirection(self.ui.grip_box.currentData()),
            friction_factor=self.ui.friction.value(),
            count_partial_as_sealed=self.ui.partial_counts.isChecked(),
            solve_operating_point=self.ui.solve_point.isChecked(),
        )
        self._request = request
        self._service.calculate_async(request, snapshot.revision)

    def _on_started(self, _ticket) -> None:
        # Das bisherige Ergebnis bleibt stehen, wird aber blass gezeichnet:
        # es gilt schon nicht mehr, ist aber besser als eine leere Flaeche.
        self.ui.view.set_stale(True)

    def _on_result(self, result: VacuumResult) -> None:
        self._result = result
        self._result_revision = result.meta.state_revision
        self._needs_recalculation = False
        self.ui.banner.hide_message()
        self.ui.view.set_result(result)
        self._show_result(result)
        # Die fertige Platte fuer den Vakuumverlauf bereitlegen - mit der
        # Anfrage, denn der Verlauf braucht Sauger, Leckage und Erzeuger.
        self._service.publish_plate(SharedPlate(request=self._request, result=result))

    def _on_failed(self, message: str) -> None:
        self.ui.results.clear_values()
        self.ui.flow_results.clear_values()
        self._show_raster_values()
        self._service.publish_plate(None)
        self.ui.banner.show_message(message)

    # Anzeige ------------------------------------------------------------------

    def _show_result(self, result: VacuumResult) -> None:
        grid = self.ui.results
        grid.set_value("status", result.status.label, _STATUS_COLORS.get(result.status, ""))
        grid.set_value("max_mass", format(result.max_package_mass_kg, ".2f") + " kg")
        # Die Last traegt die Farbe, nicht die Grenze: rot ist das Gewicht, das
        # zu schwer ist, und nicht die Platte, die nicht mehr kann.
        grid.set_value(
            "actual_mass", format(result.actual_mass_kg, ".2f") + " kg",
            _ampel(result.max_package_mass_kg, result.actual_mass_kg),
        )
        grid.set_value(
            "needed_cups",
            str(result.required_cup_count) + " von " + str(result.sealed_count) + " wirksamen",
            _ampel(result.sealed_count, result.required_cup_count),
        )

        grid.set_value("arrangement", self.ui.arrangement_box.currentText())
        # Nur die Zahl. Das "von max. N" stand hier, solange die Hoechstzahl
        # sonst nirgends auftauchte; seit sie eine eigene Zeile direkt
        # darueber hat, stuenden in zwei Zeilen untereinander dieselben 391.
        grid.set_value("cups_total", str(result.total_cup_count))
        grid.set_value("cups_sealed", str(result.sealed_count),
                       _ampel(result.sealed_count, result.required_cup_count))
        grid.set_value("cups_partial", str(result.partial_count),
                       PALETTE.warning if result.partial_count else "")
        grid.set_value("cups_open", str(result.open_count), PALETTE.error if result.open_count else "")
        grid.set_value("area", format(result.effective_area_mm2 / 100.0, ".1f") + " cm2")

        # Zwei Zahlen in einer Zeile, weil die zweite die erste erklaert:
        # sie ist der Grund, wenn die Bewertung schlechter ausfaellt, als die
        # Zeilen darueber erwarten lassen. "Max. Paketgewicht 258 kg" neben
        # "Nicht ausreichend" sieht sonst nach einem Widerspruch aus - es ist
        # aber die Summe ueber alle Sauger, und die haengt nicht ueber jedem
        # Paket.
        gesamt = len(result.package_rects)
        tragend = result.bearing_package_count
        grid.set_value(
            "packages", str(gesamt) + " / " + str(tragend),
            PALETTE.error if tragend < gesamt else "",
        )

        flows = self.ui.flow_results
        reached_target = result.achieved_vacuum_pa >= result.target_vacuum_pa - 1.0
        flows.set_value(
            "vacuum",
            format(pa_to_mbar(result.target_vacuum_pa), ".0f") + " / "
            + format(pa_to_mbar(result.achieved_vacuum_pa), ".0f") + " mbar",
            "" if reached_target else PALETTE.warning,
        )
        flows.set_value("force", format(result.force.total_holding_n, ".1f") + " N")
        flows.set_value(
            "per_cup",
            format(result.force.theoretical_per_cup_n, ".2f") + " N"
            + ("  (Sauergrenze)" if result.force.limited_by_cup_strength else ""),
            PALETTE.warning if result.force.limited_by_cup_strength else "",
        )

        flow = result.flow
        flows.set_value("flow_required", format(m3s_to_m3h(flow.total_required_m3s), ".2f") + " m3/h")
        flows.set_value("flow_available", format(m3s_to_m3h(flow.available_m3s), ".2f") + " m3/h")
        flows.set_value("flow_open", format(m3s_to_m3h(flow.open_cups_m3s + flow.partial_cups_m3s), ".2f") + " m3/h")
        flows.set_value("flow_workpiece", format(m3s_to_m3h(flow.workpiece_m3s), ".2f") + " m3/h")
        flows.set_value(
            "flow_left", format(m3s_to_m3h(flow.remaining_m3s), ".2f") + " m3/h",
            PALETTE.error if flow.remaining_m3s < 0 else PALETTE.ok,
        )
        flows.set_value("safety", format(self.ui.safety.value(), ".1f"))

        for warning in result.warnings:
            self._context.reporter.warning("vacuum", warning)

    def _is_stale(self) -> bool:
        return self._result is not None and self._result_revision != self._context.state.revision

    def _on_layer_published(self, layer: object) -> None:
        """Im Palettentab wurde neu gerechnet oder die Ebene gewechselt.

        Nur wenn das Muster der Palettierung uebernommen wird, aendert das hier
        etwas - sonst laeuft die Anordnung ohnehin ueber das eigene Raster.

        Gerechnet wird wie bei jeder anderen Eingabeaenderung: sichtbar sofort
        (entprellt), im Hintergrund erst beim naechsten Aufschlagen. Ein Tab,
        den niemand ansieht, soll keine Rechenzeit ziehen.
        """
        if not self.ui.use_pallet_pattern.isChecked():
            return
        self._needs_recalculation = True
        if self.isVisible():
            self._debouncer.trigger()

    # TabHost ------------------------------------------------------------------

    def on_state_changed(self, change: StateChange, snapshot: AppStateSnapshot) -> None:
        if MODULE_ID not in self._context.state.invalidated_channels(change):
            return
        if snapshot.package is None:
            return

        self._needs_recalculation = True
        if self.isVisible():
            self._debouncer.trigger()

    def on_activated(self) -> None:
        """Beim Aufschlagen rechnen, wenn das Angezeigte nicht mehr stimmt.

        Auch beim allerersten Aufschlagen: ein leerer Tab, der erst auf einen
        Handlung wartet, obwohl alle Eingaben vorliegen, ist eine
        ueberfluessige Huerde.
        """
        if self._result is None or self._needs_recalculation or self._is_stale():
            self.calculate()

    def commit_now(self) -> None:
        self._debouncer.flush()

    def shutdown(self) -> None:
        save_splitter(self.ui.splitter, SETTINGS_SECTION, key=SPLITTER_KEY)
        self._debouncer.cancel()
        self._service.cancel()


class VacuumModule:
    """Anmeldung des Moduls (Spezifikation 06)."""

    module_id = MODULE_ID
    title = "Vakuumplatte"
    order = 20

    def create_widget(self, context: AppContext) -> QWidget:
        return VacuumTab(context)
