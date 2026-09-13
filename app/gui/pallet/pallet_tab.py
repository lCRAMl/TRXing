"""Tab 1 - Palettierung.

Der Tab liest Paketdaten, Auswahl und Grenzwerte, ruft den PalletService und
zeigt an, was zurueckkommt. Er kennt weder den Optimierer noch die
Musterstrategien, und er rechnet nichts - auch nicht die Flaechenausnutzung,
die steht im Ergebnis.

Am Kopf sitzt das Paketformular. Es ist kein Teil dieses Tabs, sondern ein
eigenes Widget mit eigener Layoutdatei (app/gui/package/package_form.py): die
Paketdaten gelten fuer die ganze Anwendung, nicht nur fuer die Palettierung.
Der Tab nimmt es auf und reicht ihm die drei Lebenszeichen weiter, die ein Tab
von aussen bekommt - Zustandsaenderung, Uebernahme, Ende.

Eingehaengt wird es im Quelltext und nicht als hochgestufte Klasse im Designer,
weil es den AppContext braucht; der Designer kann einem Widget nur einen
Elternteil mitgeben. Dieselbe Bauweise wie bei der 3D-Szene: die Layoutdatei
haelt den Platz frei (package_host), gefuellt wird er hier.

Das Layout steht in pallet_tab.ui und wird im Qt Designer bearbeitet:

    pallet_tab.ui    Anordnung, Gruppen, Beschriftungen, Groessenrichtlinien
    pallet_tab.py    Wertebereiche, Ereignisse, Berechnung, Anzeige

Zwei Dinge, die leicht falsch gemacht werden und deshalb hier stehen:

Nachrechnen statt melden: aendert sich das Paket, wird hier neu gerechnet -
ohne Hinweisband, ohne Bestaetigung. Solange der Tab verdeckt ist, wird die
Aenderung nur vorgemerkt und beim Aufschlagen nachgeholt; Rechenzeit fuer
Ergebnisse, die niemand ansieht, waere verschenkt. Das Hinweisband bleibt den
Faellen vorbehalten, in denen es kein Ergebnis GIBT - etwa wenn das Paket auf
keine Palette passt.

Entprellung (Spezifikation 32): Aenderungen an Hoehe oder Last loesen keinen
sofortigen Rechenlauf aus, sondern einen verzoegerten. Die Palettierung ist der
teure Rechenweg der Anwendung.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QButtonGroup, QWidget

from app.dto.common import ViewMode
from app.dto.pallet import PalletResult
from app.gui.common import window_state
from app.gui.common.widgets import Debouncer, compact_combo
from app.gui.package.package_form import PackageForm
from app.gui.pallet.ui_pallet_tab import Ui_PalletTab
from app.gui.tab_manager import TabHost
from app.gui.theme import PALETTE
from app.services.app_state import AppStateSnapshot, StateChange
from app.services.context import AppContext
from app.visualization.adapters import create_scene

MODULE_ID = "pallet"

#: Anfangsbreite der Bedienspalte und der Zeichenflaeche in Bildpunkten. Der
#: Qt Designer speichert die Aufteilung eines Splitters nicht, sie muss nach
#: setupUi gesetzt werden. Verschiebt der Benutzer den Griff, gilt seine
#: Aufteilung - diese Zahlen sind nur der erste Vorschlag.
SPLITTER_SIZES = (600, 850)

#: Abschnitt, unter dem sich der Tab die Aufteilung merkt.
SETTINGS_SECTION = "PalletTab"

#: Schalterkennungen der Ansichtswahl. Der Qt Designer legt Radioknoepfe an,
#: aber keine QButtonGroup mit stabilen Nummern; die Zuordnung Nummer -> Modus
#: soll nicht an der Reihenfolge im XML haengen.
VIEW_ID_2D = 0
VIEW_ID_3D = 1

#: Steht im Hinweisband, solange kein gueltiges Paket vorliegt. Die Eingabe ist
#: seit dem Umzug des Formulars nur einen Blick entfernt - der Hinweis zeigt
#: deshalb nach oben und nicht mehr auf einen anderen Tab.
MISSING_PACKAGE = "Die Paketdaten oben sind unvollstaendig oder ungueltig."


class PalletTab(TabHost):
    """Palettierung mit 2D- und 3D-Ansicht."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._service = context.pallets
        self._result: PalletResult | None = None
        self._result_revision = -1
        self._needs_recalculation = False
        self._scene = None
        self._debouncer = Debouncer(self.calculate, max(300, context.debounce_ms), self)

        # Zusammensetzung statt Vererbung: die aus der Layoutdatei erzeugten
        # Namen liegen unter self.ui und koennen weder mit denen von QWidget
        # noch mit eigenen kollidieren.
        self.ui = Ui_PalletTab()
        self.ui.setupUi(self)

        # Als erstes, noch vor allem anderen: das Formular uebernimmt beim
        # Anlegen die angezeigten Vorgabewerte in den Zustand. Danach findet
        # _update_enabled() ein gueltiges Paket vor, statt den Tab mit
        # "keine Paketdaten" zu eroeffnen, obwohl welche dastehen.
        self._package = PackageForm(context, self.ui.package_host)
        self.ui.package_layout.addWidget(self._package)

        self._configure_layout()
        self._configure_fields()
        self._build_result_rows()
        self._connect()

        self._connect_service()
        self._fill_catalogs()
        self._sync_state_selection()
        self._update_enabled()

    # Aufbau -------------------------------------------------------------------

    def _configure_layout(self) -> None:
        """Was der Designer nicht speichern kann."""
        # Die Zeichenflaeche bekommt den Platz, den das Fenster ueber
        # Paketformular und Hinweisstreifen hinaus hat. Ohne diese Zeile teilen
        # sich die drei die Hoehe nach ihren Groessenrichtlinien - der Streifen
        # ist meist unsichtbar, wuerde aber trotzdem wachsen. Die 2 ist die
        # Stelle des Splitters im Wurzellayout: Formular, Band, Splitter.
        self.ui.root.setStretch(2, 1)
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)
        # Zieht der Benutzer den Griff, gilt seine Aufteilung - auch beim
        # naechsten Start. SPLITTER_SIZES ist nur der erste Vorschlag.
        window_state.restore_splitter(self.ui.splitter, SETTINGS_SECTION, SPLITTER_SIZES)

        # Die Bedienspalte rollt senkrecht - waagerecht nicht. Eine Rollflaeche
        # gibt die Mindestbreite ihres Inhalts nicht nach aussen weiter; ohne
        # diese Zeile laesst sich der Griff des Splitters so weit nach links
        # ziehen, dass Beschriftungen und Ergebniswerte abgeschnitten werden.
        # Die Breite des senkrechten Rollbalkens kommt dazu, sonst fehlt genau
        # sie, sobald er erscheint.
        scroll = self.ui.controls_scroll
        scroll.setMinimumWidth(
            self.ui.controls.minimumSizeHint().width()
            + scroll.verticalScrollBar().sizeHint().width()
        )

        # Lange Eintraege duerfen die Bedienspalte nicht auseinanderziehen. Die
        # Groessenrichtlinie steht bereits in der .ui-Datei; compact_combo
        # ergaenzt den Tooltip, der den vollstaendigen Text zeigt.
        compact_combo(self.ui.pallet_box)
        compact_combo(self.ui.pattern_box)

        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self.ui.button_2d, VIEW_ID_2D)
        self._view_group.addButton(self.ui.button_3d, VIEW_ID_3D)

    def _configure_fields(self) -> None:
        """Wertebereiche, Einheiten und Erklaerungen der Eingabefelder.

        Sie stehen hier und nicht in der XML-Datei: dass eine Hoehe in
        Millimetern angegeben wird und eine Null "nimm den Wert der Palette"
        bedeutet, ist Fachwissen und keine Gestaltung.
        """
        self.ui.max_height.configure(
            "mm", minimum=0.0, maximum=10000.0, decimals=0, step=50.0,
            tooltip="0 uebernimmt den Wert des Palettentyps",
        )
        self.ui.max_load.configure(
            "kg", minimum=0.0, maximum=100000.0, decimals=0, step=50.0,
            tooltip="0 uebernimmt den Wert des Palettentyps",
        )
        self.ui.gap.configure(
            "mm", minimum=0.0, maximum=200.0, decimals=1, step=1.0,
            tooltip="Lichter Mindestabstand zwischen zwei Paketen",
        )
        self.ui.desired.configure(
            "Stueck", minimum=0, maximum=100000, value=0,
            special_zero_text="so viele wie moeglich",
        )

        available = self._service.solver_available()
        self.ui.use_solver.setEnabled(available)
        self.ui.use_solver.setToolTip(
            "Sucht die dichteste Lage mit einem Constraint-Loeser. Deterministisch "
            "eingestellt, dafuer langsamer als die Heuristik."
            if available else
            "Nicht verfuegbar - das Paket ortools ist nicht installiert."
        )

    def _build_result_rows(self) -> None:
        """Die Zeilen der Ergebnisanzeige.

        Sie stehen hier und nicht in der Layoutdatei: es sind Daten, keine
        Anordnung. Der Designer bestimmt, wo das Raster sitzt und wie es heisst.
        """
        grid = self.ui.results
        grid.add_row("total", "Pakete gesamt")
        grid.add_row("per_layer", "Pakete je Lage")
        grid.add_row("layers", "Anzahl Lagen")
        grid.add_separator()
        grid.add_row("weight", "Gesamtgewicht")
        grid.add_row("height", "Gesamthoehe mit Palette")
        grid.add_row("load_height", "Stapelhoehe")
        grid.add_separator()
        grid.add_row("utilization", "Flaechenausnutzung")
        grid.add_row("volume", "Raumausnutzung")
        grid.add_row("max_load", "Hoechste Paketbelastung")
        grid.add_row("limit", "Begrenzt durch")

    def _connect(self) -> None:
        self.ui.calculate_button.clicked.connect(self.calculate)
        self.ui.cancel_button.clicked.connect(self._service.cancel)

        self.ui.pallet_box.currentIndexChanged.connect(self._on_pallet_changed)
        self.ui.pattern_box.currentIndexChanged.connect(self._on_pattern_changed)
        for field in (self.ui.max_height, self.ui.max_load, self.ui.gap, self.ui.desired):
            field.value_changed.connect(lambda *_: self._debouncer.trigger())
        self.ui.use_solver.toggled.connect(lambda *_: self._debouncer.trigger())

        self.ui.layer_box.currentIndexChanged.connect(self._on_layer_changed)
        self.ui.reset_camera.clicked.connect(self._on_reset_camera)
        self._view_group.idToggled.connect(self._on_view_changed)

    def _connect_service(self) -> None:
        self._service.started.connect(self._on_started)
        self._service.result_ready.connect(self._on_result)
        self._service.failed.connect(self._on_failed)
        self._service.superseded.connect(lambda _request_id: None)

    def _fill_catalogs(self) -> None:
        self.ui.pallet_box.blockSignals(True)
        self.ui.pattern_box.blockSignals(True)
        self.ui.pallet_box.clear()
        self.ui.pattern_box.clear()
        for pallet in self._service.available_pallets():
            self.ui.pallet_box.addItem(pallet.name, pallet.id)
        for pattern in self._service.available_patterns():
            self.ui.pattern_box.addItem(pattern.name, pattern.id)
        self.ui.pallet_box.blockSignals(False)
        self.ui.pattern_box.blockSignals(False)
        self._on_pallet_changed()
        self._on_pattern_changed()

    # Auswahl ------------------------------------------------------------------

    def _current_pallet(self):
        return self._context.settings.get_pallet(self.ui.pallet_box.currentData())

    def _current_pattern(self):
        return self._context.settings.get_pattern(self.ui.pattern_box.currentData())

    def _on_pallet_changed(self, *_args) -> None:
        pallet = self._current_pallet()
        if pallet is None:
            return
        self._context.state.set_pallet_id(pallet.id)
        # Die Grenzwerte des Palettentyps als Vorschlag uebernehmen, solange der
        # Benutzer nichts Eigenes eingetragen hat. Eine Null heisst weiterhin
        # "nimm den Wert der Palette" - der Vorschlag macht ihn nur sichtbar.
        if self.ui.max_height.value() <= 0:
            self.ui.max_height.set_value(pallet.max_load_height_mm)
        if self.ui.max_load.value() <= 0:
            self.ui.max_load.set_value(pallet.max_load_kg)
        self._debouncer.trigger()

    def _on_pattern_changed(self, *_args) -> None:
        pattern = self._current_pattern()
        if pattern is None:
            return
        self._context.state.set_pattern_id(pattern.id)
        self.ui.pattern_hint.setText(pattern.description)
        self._debouncer.trigger()

    def _sync_state_selection(self) -> None:
        snapshot = self._context.state.snapshot()
        if snapshot.pallet_id:
            index = self.ui.pallet_box.findData(snapshot.pallet_id)
            if index >= 0:
                self.ui.pallet_box.setCurrentIndex(index)
        if snapshot.pattern_id:
            index = self.ui.pattern_box.findData(snapshot.pattern_id)
            if index >= 0:
                self.ui.pattern_box.setCurrentIndex(index)

    # Berechnung ---------------------------------------------------------------

    def calculate(self) -> None:
        self._debouncer.cancel()
        snapshot = self._context.state.snapshot()
        package = snapshot.package
        pallet = self._current_pallet()
        pattern = self._current_pattern()

        if package is None:
            self.ui.banner.show_message(MISSING_PACKAGE)
            self._service.invalidate()
            return
        if pallet is None or pattern is None:
            self.ui.banner.show_message("Palettentyp oder Muster fehlt - Konfiguration pruefen.")
            return

        constraints = self._service.build_constraints(
            pallet, package,
            max_height_mm=self.ui.max_height.value(),
            max_load_kg=self.ui.max_load.value(),
            gap_mm=self.ui.gap.value(),
            desired_count=self.ui.desired.value(),
            use_solver=self.ui.use_solver.isChecked(),
        )
        self._service.calculate_async(package, pallet, pattern, constraints, snapshot.revision)

    def _on_started(self, ticket) -> None:
        self.ui.cancel_button.setEnabled(True)
        self.ui.calculate_button.setEnabled(False)
        # Waehrend gerechnet wird, wird das bisherige Ergebnis blass gezeichnet -
        # es steht noch da, gilt aber schon nicht mehr.
        self.ui.view_2d.set_stale(True)
        if self._scene is not None:
            self._scene.set_stale(True)

    def _on_result(self, result: PalletResult) -> None:
        self.ui.cancel_button.setEnabled(False)
        self.ui.calculate_button.setEnabled(True)
        self._result = result
        self._result_revision = result.meta.state_revision
        self._needs_recalculation = False
        self.ui.banner.hide_message()
        self._show_result(result)

    def _on_failed(self, message: str) -> None:
        self.ui.cancel_button.setEnabled(False)
        self.ui.calculate_button.setEnabled(True)
        self.ui.results.clear_values()
        self.ui.banner.show_message(message)

    # Anzeige ------------------------------------------------------------------

    def _show_result(self, result: PalletResult) -> None:
        grid = self.ui.results
        grid.set_value("total", str(result.total_count))
        grid.set_value("per_layer", str(result.per_layer_count))
        grid.set_value("layers", str(result.layer_count))
        grid.set_value("weight", format(result.total_weight_kg, ".1f") + " kg")
        grid.set_value("height", format(result.total_height_mm, ".0f") + " mm")
        grid.set_value("load_height", format(result.total_load_height_mm, ".0f") + " mm")
        grid.set_value("utilization", format(result.footprint_utilization_ratio * 100.0, ".1f") + " %")
        grid.set_value("volume", format(result.volume_utilization_ratio * 100.0, ".1f") + " %")

        if result.load.checked:
            colour = PALETTE.error if result.load.critical_count else (
                PALETTE.warning if result.load.warning_count else PALETTE.ok
            )
            grid.set_value("max_load", format(result.load.max_load_pct, ".1f") + " %", colour)
        else:
            grid.set_value("max_load", "nicht geprueft")
        grid.set_value("limit", result.limiting_factor.label)

        self.ui.layer_box.blockSignals(True)
        self.ui.layer_box.clear()
        for layer in result.layers:
            self.ui.layer_box.addItem(
                "Ebene " + str(layer.index + 1) + "  (" + str(layer.count) + ")", layer.index
            )
        self.ui.layer_box.blockSignals(False)

        self.ui.view_2d.set_result(result)
        if self._scene is not None:
            self._scene.set_result(result)

        for warning in result.warnings:
            self._context.reporter.warning("pallet", warning)

    def _on_layer_changed(self, index: int) -> None:
        if index < 0:
            return
        layer_index = self.ui.layer_box.itemData(index)
        self.ui.view_2d.set_layer(int(layer_index or 0))

    def _on_view_changed(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        mode = ViewMode.TOP_2D if button_id == VIEW_ID_2D else ViewMode.SCENE_3D
        self.ui.reset_camera.setVisible(mode is ViewMode.SCENE_3D)
        self.ui.layer_box.setEnabled(mode is ViewMode.TOP_2D)

        if mode is ViewMode.SCENE_3D and self._scene is None:
            self._create_scene()
        self.ui.views.setCurrentIndex(0 if mode is ViewMode.TOP_2D else 1)

    def _create_scene(self) -> None:
        """Baut die 3D-Ansicht beim ersten Oeffnen.

        Die Seite im Stapel bleibt bis dahin leer. VTK wird erst geladen, wenn
        jemand die Ansicht tatsaechlich oeffnet - das spart beim Start mehrere
        Sekunden fuer alle, die nur die Draufsicht brauchen.
        """
        self._scene = create_scene(self.ui.scene_host)
        self.ui.scene_layout.addWidget(self._scene.widget())
        if self._result is not None:
            self._scene.set_result(self._result)
            self._scene.set_stale(self._is_stale())

    def _on_reset_camera(self) -> None:
        if self._scene is not None:
            self._scene.reset_camera()

    def _update_enabled(self) -> None:
        has_package = self._context.state.snapshot().package is not None
        self.ui.calculate_button.setEnabled(has_package)
        if not has_package:
            self.ui.banner.show_message(MISSING_PACKAGE)

    def _is_stale(self) -> bool:
        return self._result is not None and self._result_revision != self._context.state.revision

    # TabHost ------------------------------------------------------------------

    def on_state_changed(self, change: StateChange, snapshot: AppStateSnapshot) -> None:
        # Zuerst das Formular: setzt jemand anders das Paket, zieht seine
        # Anzeige nach. Das gilt auch fuer Aenderungen, die diesen Tab nichts
        # angehen - deshalb vor der Abfrage unten.
        self._package.on_state_changed(change, snapshot)

        if MODULE_ID not in self._context.state.invalidated_channels(change):
            return
        self._update_enabled()
        if snapshot.package is None:
            return

        self._needs_recalculation = True
        if self.isVisible():
            self._debouncer.trigger()

    def on_activated(self) -> None:
        """Beim Aufschlagen rechnen, wenn das Angezeigte nicht mehr stimmt.

        Auch beim allerersten Aufschlagen: ein leerer Tab, der erst auf einen
        Klick auf "Berechnen" wartet, obwohl alle Eingaben vorliegen, ist eine
        ueberfluessige Huerde.
        """
        if self._result is None or self._needs_recalculation or self._is_stale():
            self.calculate()

    def commit_now(self) -> None:
        # Das Formular zuerst: seine Uebernahme setzt das Paket, und die eigene
        # Rechnung soll mit dem neuen laufen, nicht mit dem vorigen.
        self._package.commit_now()
        self._debouncer.flush()

    def shutdown(self) -> None:
        window_state.save_splitter(self.ui.splitter, SETTINGS_SECTION)
        self._package.shutdown()
        self._debouncer.cancel()
        self._service.cancel()
        if self._scene is not None:
            self._scene.shutdown()


class PalletModule:
    """Anmeldung des Moduls (Spezifikation 06)."""

    module_id = MODULE_ID
    title = "Palettierung"
    order = 10

    def create_widget(self, context: AppContext) -> QWidget:
        return PalletTab(context)
