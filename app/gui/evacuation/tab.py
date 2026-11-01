"""Vakuumverlauf ueber der Zeit.

Die dritte Ansicht derselben Scheibe: Tab 2 sagt, WO sich das Vakuum
einpendelt, dieser Tab sagt, WIE LANGE es dahin braucht und was der
Frequenzumrichter daran aendert.

Gerechnet wird auf der Platte, die Tab 2 zuletzt fertiggestellt hat - sie
liegt im Dienst bereit (publish_plate). Dieser Tab baut sich keine zweite
Platte aus denselben Eingaben zusammen; er haette sonst seine eigene Meinung
zur Saugerzahl, und zwei Tabs mit zwei Meinungen ueber dieselbe Platte sind
schlimmer als ein leerer Tab.

Was er selbst beitraegt, sind die Groessen, die es auf Tab 2 nicht gibt:
das Systemvolumen und die Frequenz.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QScrollArea, QSplitter, QVBoxLayout, QWidget

from app.context import AppContext
from app.domain.state import AppStateSnapshot, StateChange
from app.domain.units import m3s_to_m3h, pa_to_mbar
from app.gui.form_builder import Gruppe, Oberflaeche, Regler, Zahl, baue
from app.gui.theme import PALETTE
from app.gui.window_state import fit_controls_column, save_splitter
from app.tab_registry import TabHost
from app.vacuum.models import SystemVolumeSpec
from qt_controls_pyrs import CompactResultGrid, HaloChart, StaleBanner

MODULE_ID = "evacuation"

#: Anfangsbreite der Zeichenflaeche. Die Bedienspalte misst sich selbst -
#: siehe _configure_layout().
VIEW_WIDTH = 830

SETTINGS_SECTION = "EvacuationTab"
SPLITTER_KEY = "splitter_narrow_column"

#: Grenzen des Frequenzreglers in Hertz.
#:
#: 25 Hz unten: darunter kuehlt ein eigengekuehlter Motor nicht mehr genug.
#: 100 Hz oben: so gewuenscht. Ab 60 Hz gibt es keine Datenblattwerte mehr -
#: gerechnet wird weiter, das Endvakuum bleibt aber beim Datenblattwert
#: gedeckelt (siehe physics.pump_at_frequency).
FREQUENCY_MIN_HZ = 25.0
FREQUENCY_MAX_HZ = 100.0

#: Der Regler kennt nur ganze Zahlen, die Frequenz hat eine Nachkommastelle.
#: Er laeuft deshalb in Zehntelhertz; das Feld rechnet um.
FREQUENCY_STEPS_PER_HZ = 10

#: Ab diesem Anteil des Endwerts bringt Warten fast nichts mehr. Der Bereich
#: wird im Diagramm hinterlegt - er ist die eigentliche Antwort auf die Frage
#: "wie lange muss ich saugen".
SATURATION_RATIO = 0.95

BEDIENSPALTE = [
    Gruppe("Systemvolumen", [
        [Zahl("box_height", "Saugkastenhoehe", "mm", dict(
            min=0.0, max=2000.0, stellen=0, schritt=10.0,
            hinweis="Hoehe des Hohlraums ueber der Platte.\n"
                    "Anlagenangabe, keine Datenblattgroesse.")),
         Zahl("hose_length", "Schlauchlaenge", "m", dict(
            min=0.0, max=200.0, stellen=1, schritt=0.5,
            hinweis="Laenge vom Erzeuger bis zur Platte."))],
        [Zahl("hose_diameter", "Schlauchdurchmesser", "mm", dict(
            min=1.0, max=1000.0, stellen=0, schritt=5.0,
            hinweis="Geht NUR ins Volumen ein - ein Druckverlust im Schlauch\n"
                    "wird nicht gerechnet. Ein dickerer Schlauch macht die\n"
                    "Platte in diesem Modell also langsamer, nicht schneller.")),
         Zahl("extra_volume", "Zusatzvolumen", "l", dict(
            min=0.0, max=10000.0, stellen=1, schritt=1.0,
            hinweis="Alles, was sonst noch leergesaugt wird - vor allem das\n"
                    "Innere der Sauger. Das Datenblatt nennt dazu keinen Wert,\n"
                    "deshalb steht hier 0 und keine Schaetzung."))],
    ], name="volume_box", oben=True),

    Gruppe("Frequenzumrichter", [
        [Zahl("frequency", "Frequenz", "Hz", dict(
            min=FREQUENCY_MIN_HZ, max=FREQUENCY_MAX_HZ, stellen=1, schritt=1.0,
            hinweis="Saugvermoegen steigt mit der Drehzahl, das Endvakuum\n"
                    "unterhalb 50 Hz mit dem Quadrat. Darueber bleibt es beim\n"
                    "Datenblattwert - gemessen an 28 Geraeten mit Angaben fuer\n"
                    "50 und 60 Hz."))],
        [Regler("frequency_slider",
                min=int(FREQUENCY_MIN_HZ * FREQUENCY_STEPS_PER_HZ),
                max=int(FREQUENCY_MAX_HZ * FREQUENCY_STEPS_PER_HZ),
                wert=50 * FREQUENCY_STEPS_PER_HZ,
                hinweis="Stufenlos zwischen "
                        + format(FREQUENCY_MIN_HZ, "g") + " und "
                        + format(FREQUENCY_MAX_HZ, "g") + " Hz.")],
    ], name="frequency_box", oben=True),
]

#: Die Zeilen der Ergebnisanzeige. None ist eine Trennlinie.
ERGEBNISZEILEN = [
    ("volume", "Systemvolumen"),
    ("box", "davon Saugkasten"),
    ("hose", "davon Schlauch"),
    ("extra", "davon Zusatz"),
    None,
    ("flow", "Saugvermoegen"),
    ("max_vacuum", "Endvakuum des Erzeugers"),
    ("final", "Arbeitspunkt"),
    None,
    ("t90", "Zeit bis 90 Prozent"),
    ("t99", "Zeit bis 99 Prozent"),
]


class EvacuationTab(TabHost):
    """Vakuumverlauf mit Frequenzregler und Diagramm."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._service = context.vacuum
        self._curve = None

        self.ui = Oberflaeche()
        self._build_layout()
        self._configure_layout()
        self._build_result_rows()
        self._apply_defaults()
        self._connect()
        self.recalculate()

    # Aufbau -------------------------------------------------------------------

    def _build_layout(self) -> None:
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

        self.ui.chart = HaloChart()
        self.ui.chart.set_labels("Zeit [s]", "Vakuum [mbar]")
        self.ui.view_layout.addWidget(self.ui.chart, 1)

        self.ui.result_row = QHBoxLayout()
        self.ui.result_row.setSpacing(6)
        self.ui.results = CompactResultGrid("Ergebnis")
        self.ui.result_row.addWidget(self.ui.results)
        self.ui.view_layout.addLayout(self.ui.result_row)

        self.ui.splitter.addWidget(self.ui.view_panel)

    def _configure_layout(self) -> None:
        self.ui.root.setStretch(1, 1)
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)

        fit_controls_column(
            self.ui.splitter, self.ui.controls_scroll, self.ui.controls,
            VIEW_WIDTH, SETTINGS_SECTION, key=SPLITTER_KEY,
        )

    def _build_result_rows(self) -> None:
        for eintrag in ERGEBNISZEILEN:
            if eintrag is None:
                self.ui.results.add_separator()
            else:
                self.ui.results.add_row(*eintrag)

    def _apply_defaults(self) -> None:
        defaults = self._service.defaults()
        volumen = defaults.system_volume
        self.ui.box_height.set_value(volumen.box_height_mm)
        self.ui.hose_length.set_value(volumen.hose_length_m)
        self.ui.hose_diameter.set_value(volumen.hose_diameter_mm)
        self.ui.extra_volume.set_value(volumen.extra_volume_l)
        self.ui.frequency.set_value(defaults.frequency_hz)
        self._show_frequency_on_slider()

    def _connect(self) -> None:
        for feld in (self.ui.box_height, self.ui.hose_length,
                     self.ui.hose_diameter, self.ui.extra_volume):
            feld.value_changed.connect(lambda *_: self.recalculate())
        self.ui.frequency.value_changed.connect(self._on_frequency_typed)
        self.ui.frequency_slider.valueChanged.connect(self._on_slider_moved)
        self._service.plate_published.connect(self._on_plate_published)

    # Eingaben -----------------------------------------------------------------

    def _current_volume(self) -> SystemVolumeSpec:
        return SystemVolumeSpec(
            box_height_mm=self.ui.box_height.value(),
            hose_length_m=self.ui.hose_length.value(),
            hose_diameter_mm=self.ui.hose_diameter.value(),
            extra_volume_l=self.ui.extra_volume.value(),
        )

    def _show_frequency_on_slider(self) -> None:
        """Den Regler auf das Feld stellen, ohne ihn antworten zu lassen.

        Ohne blockSignals liefe die Kette Feld -> Regler -> Feld. Der WERT
        bliebe dabei richtig - Feld und Regler haben dieselbe Aufloesung von
        einem Zehntelhertz, der Rueckweg traegt also dieselbe Zahl ein. Was
        sich aendert, ist die Zahl der Rechnungen: jede getippte Ziffer
        liefe zweimal durch recalculate(). Die Gegenprobe ohne diese Zeile
        blieb am Wert gruen und faellt an der Zaehlung.
        """
        self.ui.frequency_slider.blockSignals(True)
        self.ui.frequency_slider.setValue(
            round(self.ui.frequency.value() * FREQUENCY_STEPS_PER_HZ)
        )
        self.ui.frequency_slider.blockSignals(False)

    def _on_frequency_typed(self, *_args) -> None:
        self._show_frequency_on_slider()
        self.recalculate()

    def _on_slider_moved(self, schritte: int) -> None:
        self.ui.frequency.blockSignals(True)
        self.ui.frequency.set_value(schritte / FREQUENCY_STEPS_PER_HZ)
        self.ui.frequency.blockSignals(False)
        self.recalculate()

    def _on_plate_published(self, _plate) -> None:
        if self.isVisible():
            self.recalculate()

    # Rechnung und Anzeige -----------------------------------------------------

    def recalculate(self) -> None:
        """Den Verlauf neu bestimmen und zeichnen.

        Synchron: eine Quadratur ueber 400 Stuetzstellen dauert Mikrosekunden.
        Eine Entprellung waere hier nur ein zweiter Weg zum selben Ergebnis.
        """
        plate = self._service.published_plate()
        if plate is None:
            self._curve = None
            self.ui.chart.clear()
            self.ui.results.clear_values()
            self.ui.banner.show_message(
                "Noch keine gerechnete Platte - siehe Tab 'Vakuumplatte'."
            )
            return

        self.ui.banner.hide_message()
        self._curve = self._service.evacuation_curve(
            plate, self._current_volume(), self.ui.frequency.value()
        )
        self._show_curve(plate)

    def _show_curve(self, plate) -> None:
        kurve = self._curve
        diagramm = self.ui.chart
        diagramm.clear()

        if kurve.points:
            diagramm.add_series(
                "Vakuum",
                [(punkt.time_s, pa_to_mbar(punkt.vacuum_pa)) for punkt in kurve.points],
                PALETTE.ok,
            )
            ende_mbar = pa_to_mbar(kurve.final_vacuum_pa)
            diagramm.add_band(
                ende_mbar * SATURATION_RATIO, ende_mbar,
                label="Saettigung", color=PALETTE.warning,
            )
            soll_mbar = pa_to_mbar(plate.request.target_vacuum_pa)
            if soll_mbar > ende_mbar + 1.0:
                # Nur wenn es etwas zu sehen gibt: liegt das Sollvakuum auf
                # dem Endwert, laege die Linie genau auf dem Rand des Bandes.
                diagramm.add_rule(soll_mbar, label="Sollvakuum", color=PALETTE.error)

        raster = self.ui.results
        raster.set_value("volume", format(kurve.volume_m3 * 1000.0, ".1f") + " l")
        raster.set_value("box", format(kurve.box_volume_m3 * 1000.0, ".1f") + " l")
        raster.set_value("hose", format(kurve.hose_volume_m3 * 1000.0, ".1f") + " l")
        raster.set_value("extra", format(kurve.extra_volume_m3 * 1000.0, ".1f") + " l")

        raster.set_value("flow", format(m3s_to_m3h(kurve.nominal_flow_m3s), ".0f") + " m3/h")
        raster.set_value("max_vacuum", format(pa_to_mbar(kurve.max_vacuum_pa), ".0f") + " mbar")
        raster.set_value("final", format(pa_to_mbar(kurve.final_vacuum_pa), ".0f") + " mbar")
        raster.set_value("t90", _zeit(kurve.time_to_90_s))
        raster.set_value("t99", _zeit(kurve.time_to_99_s))

        if kurve.notes:
            self.ui.banner.show_message(kurve.notes[0])

    # TabHost ------------------------------------------------------------------

    def on_state_changed(self, _change: StateChange, _snapshot: AppStateSnapshot) -> None:
        """Nichts zu tun.

        Der Verlauf haengt nicht am Zustand, sondern an der fertigen Platte -
        und die meldet sich selbst ueber plate_published.
        """

    def on_activated(self) -> None:
        self.recalculate()

    def shutdown(self) -> None:
        save_splitter(self.ui.splitter, SETTINGS_SECTION, key=SPLITTER_KEY)


def _zeit(sekunden: float) -> str:
    """Sekunden oder Millisekunden - je nachdem, was man lesen kann."""
    if sekunden <= 0.0:
        return "-"
    if sekunden < 1.0:
        return format(sekunden * 1000.0, ".0f") + " ms"
    return format(sekunden, ".2f") + " s"


class EvacuationModule:
    """Anmeldung des Moduls (Spezifikation 06)."""

    module_id = MODULE_ID
    title = "Vakuumverlauf"
    order = 30

    def create_widget(self, context: AppContext) -> QWidget:
        return EvacuationTab(context)
