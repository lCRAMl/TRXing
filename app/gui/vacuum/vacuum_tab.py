"""Tab 2 - Vakuumplatte.

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

from PyQt6.QtWidgets import QWidget

from app.core.result import Status
from app.core.units import m3s_to_m3h, mbar_to_pa, pa_to_mbar
from app.dto.suction import RestrictorMode, RestrictorSpec
from app.dto.vacuum import GripDirection, LeakageSpec, VacuumInput, VacuumPlateSpec, VacuumResult
from app.gui.common import window_state
from app.gui.common.widgets import Debouncer, compact_combo
from app.gui.tab_manager import TabHost
from app.gui.theme import PALETTE
from app.gui.vacuum.ui_vacuum_tab import Ui_VacuumTab
from app.services.app_state import AppStateSnapshot, StateChange
from app.services.context import AppContext

MODULE_ID = "vacuum"

#: Anfangsbreite von Bedienspalte und Zeichenflaeche. Der Qt Designer speichert
#: die Aufteilung eines Splitters nicht; sie wird nach setupUi gesetzt und gilt
#: nur, bis der Benutzer den Griff verschiebt.
#:
#: Die 460 sind gemessen, nicht geschaetzt: die breiteste Zeile der Bedienspalte
#: ist das Kontrollkaestchen "Arbeitspunkt loesen statt Sollvakuum annehmen"
#: neben seiner Beschriftungsspalte. Bleibt darunter, erscheint schon beim
#: Start ein waagerechter Rollbalken - bei einer Spalte, die ohnehin senkrecht
#: rollt, sieht das nach einem Fehler aus.
SPLITTER_SIZES = (460, 830)

#: Abschnitt, unter dem sich der Tab die Aufteilung merkt.
SETTINGS_SECTION = "VacuumTab"

_STATUS_COLORS = {
    Status.SAFE: PALETTE.ok,
    Status.MARGINAL: PALETTE.warning,
    Status.INSUFFICIENT: PALETTE.error,
}


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
        self._debouncer = Debouncer(self.calculate, context.debounce_ms, self)

        # Zusammensetzung statt Vererbung: die aus der Layoutdatei erzeugten
        # Namen liegen unter self.ui und koennen weder mit denen von QWidget
        # noch mit eigenen kollidieren.
        self.ui = Ui_VacuumTab()
        self.ui.setupUi(self)

        self._configure_layout()
        self._configure_fields()
        self._build_result_rows()
        self._connect()

        self._connect_service()
        self._fill_catalogs()
        self._apply_defaults()
        self._update_cup_limit()

    # Aufbau -------------------------------------------------------------------

    def _configure_layout(self) -> None:
        """Was der Designer nicht speichern kann."""
        # Die Zeichenflaeche bekommt den Platz, den das Fenster ueber den
        # Hinweisstreifen hinaus hat.
        self.ui.root.setStretch(1, 1)
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)
        # Zieht der Benutzer den Griff, gilt seine Aufteilung - auch beim
        # naechsten Start. SPLITTER_SIZES ist nur der erste Vorschlag.
        window_state.restore_splitter(self.ui.splitter, SETTINGS_SECTION, SPLITTER_SIZES)

        # Lange Eintraege duerfen die Bedienspalte nicht auseinanderziehen; die
        # Groessenrichtlinie dafuer steht in der .ui-Datei. compact_combo
        # ergaenzt den Tooltip mit dem vollstaendigen Text - ausser dort, wo im
        # Designer bereits eine Erklaerung hinterlegt ist.
        for combo in (self.ui.cup_box, self.ui.arrangement_box, self.ui.restrictor_box,
                      self.ui.leakage_box, self.ui.grip_box):
            compact_combo(combo)

    def _configure_fields(self) -> None:
        """Wertebereiche, Einheiten und Erklaerungen der Eingabefelder.

        Sie stehen hier und nicht in der XML-Datei: dass ein Vakuum in Millibar
        angegeben wird, hoechstens 1000 betragen kann und die Datenblattkraefte
        keinen Sicherheitsfaktor enthalten, ist Fachwissen und keine Gestaltung.
        """
        self.ui.plate_length.configure("mm", minimum=10.0, maximum=3000.0, decimals=0, step=10.0)
        self.ui.plate_width.configure("mm", minimum=10.0, maximum=3000.0, decimals=0, step=10.0)
        self.ui.edge_margin.configure("mm", minimum=0.0, maximum=500.0, decimals=0, step=5.0)
        self.ui.min_spacing.configure(
            "mm", minimum=0.0, maximum=500.0, decimals=0, step=1.0,
            tooltip="Lichter Abstand zwischen den Aussenmassen zweier Sauger.\n"
                    "0 bedeutet: die Sauger stossen aneinander.",
        )

        self.ui.cup_count.configure(
            "Stueck", minimum=0, maximum=20000, value=0,
            special_zero_text="automatisch (maximal)",
        )
        self.ui.package_count.configure("Stueck", minimum=1, maximum=200, value=1)

        self.ui.vacuum.configure(
            "mbar", minimum=10.0, maximum=1000.0, decimals=0, step=25.0,
            tooltip="Unterdruck gegenueber der Umgebung. Datenblattwerte gelten bei 600 mbar.",
        )
        self.ui.flow.configure(
            "m3/h", minimum=0.0, maximum=1000.0, decimals=2, step=1.0,
            tooltip="Nennvolumenstrom des Erzeugers bei geringem Unterdruck.",
        )
        self.ui.permeability.configure("", minimum=0.0, maximum=100.0, decimals=3, step=0.05)
        self.ui.safety.configure(
            "", minimum=1.0, maximum=20.0, decimals=1, step=0.5,
            tooltip="Die Datenblattkraefte enthalten ausdruecklich KEINEN Sicherheitsfaktor.\n"
                    "Er wird hier gesondert angesetzt.",
        )
        self.ui.acceleration.configure(
            "m/s2", minimum=0.0, maximum=200.0, decimals=2, step=0.5,
            tooltip="Zusaetzliche Beschleunigung der Handhabung. 0 ergibt die rein statische Rechnung.",
        )
        self.ui.friction.configure(
            "", minimum=0.01, maximum=2.0, decimals=2, step=0.05,
            tooltip="Reibbeiwert Sauger gegen Karton. Benutzerangabe, keine Datenblattgroesse.",
        )

    def _build_result_rows(self) -> None:
        """Die Zeilen beider Ergebnisraster.

        Sie stehen hier und nicht in der Layoutdatei: es sind Daten, keine
        Anordnung. Die Aufteilung in zwei Spalten ist dagegen Gestaltung und
        steht in der .ui-Datei - untereinander waeren es ueber zwanzig Zeilen,
        und man wuerde beim Vergleichen scrollen.
        """
        grid = self.ui.results
        grid.add_row("status", "Bewertung")
        grid.add_row("max_mass", "Max. Paketgewicht")
        grid.add_row("actual_mass", "Tatsaechliches Gewicht")
        grid.add_row("needed_cups", "Benoetigte wirksame Sauger")
        grid.add_separator()
        grid.add_row("arrangement", "Saugermuster")
        grid.add_row("cups_total", "Sauger gesamt")
        grid.add_row("cups_sealed", "Wirksame Sauger")
        grid.add_row("cups_partial", "Teilweise aufliegend")
        grid.add_row("cups_open", "Offene Sauger")
        grid.add_row("area", "Effektive Saugflaeche")
        grid.add_separator()
        grid.add_row("packages", "Pakete unter der Platte")

        flows = self.ui.flow_results
        flows.add_row("vacuum", "Vakuum (Soll / erreicht)")
        flows.add_row("force", "Haltekraft")
        flows.add_row("per_cup", "davon je Sauger")
        flows.add_separator()
        flows.add_row("flow_required", "Volumenstrom benoetigt")
        flows.add_row("flow_available", "Volumenstrom verfuegbar")
        flows.add_row("flow_open", "davon offene Sauger")
        flows.add_row("flow_workpiece", "davon Karton")
        flows.add_row("flow_left", "Verbleibend")
        flows.add_separator()
        flows.add_row("safety", "Sicherheitsfaktor")

    def _connect(self) -> None:
        self.ui.calculate_button.clicked.connect(self.calculate)

        self.ui.cup_box.currentIndexChanged.connect(self._on_cup_changed)
        self.ui.arrangement_box.currentIndexChanged.connect(self._on_arrangement_changed)
        self.ui.leakage_box.currentIndexChanged.connect(self._on_leakage_changed)
        self.ui.grip_box.currentIndexChanged.connect(self._on_grip_changed)
        self.ui.restrictor_box.currentIndexChanged.connect(lambda *_: self._debouncer.trigger())

        # Die Plattenmasse aendern, wie viele Sauger ueberhaupt passen - sie
        # brauchen deshalb einen eigenen Weg, nicht nur die Neuberechnung.
        for field in (self.ui.plate_length, self.ui.plate_width,
                      self.ui.edge_margin, self.ui.min_spacing):
            field.value_changed.connect(self._on_plate_changed)

        for field in (self.ui.cup_count, self.ui.package_count, self.ui.vacuum, self.ui.flow,
                      self.ui.permeability, self.ui.safety, self.ui.acceleration, self.ui.friction):
            field.value_changed.connect(lambda *_: self._debouncer.trigger())

        for box in (self.ui.use_pallet_pattern, self.ui.partial_counts, self.ui.solve_point):
            box.toggled.connect(lambda *_: self._debouncer.trigger())

    def _connect_service(self) -> None:
        self._service.started.connect(self._on_started)
        self._service.result_ready.connect(self._on_result)
        self._service.failed.connect(self._on_failed)

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
        self.ui.min_spacing.set_value(defaults.plate.min_spacing_mm)
        self.ui.vacuum.set_value(pa_to_mbar(defaults.target_vacuum_pa))
        self.ui.flow.set_value(m3s_to_m3h(defaults.pump.nominal_flow_m3s))
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
            min_spacing_mm=self.ui.min_spacing.value(),
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
        self.ui.cup_info.setText(
            "Datenblatt: " + format(cup.theoretical_force_n, "g") + " N bei -"
            + format(pa_to_mbar(cup.reference_vacuum_pa) / 1000.0, ".1f").replace(".", ",") + " bar   |   "
            "Dichtlippe " + format(cup.sealing_lip_diameter_mm, "g") + " mm   |   "
            "Aussen unter Vakuum " + format(cup.outer_diameter_mm, "g") + " mm   |   "
            "Bohrung " + format(cup.bore_diameter_mm, "g") + " mm   |   "
            "Abreisskraft " + format(cup.pull_off_force_n, "g") + " N"
        )
        self._update_cup_limit()
        self._debouncer.trigger()

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
                self.ui.arrangement_info.setText(description)
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
        cup = self._current_cup()
        if cup is None:
            return
        plate = self._current_plate()
        arrangement = self._current_arrangement()

        maximum = self._service.max_cup_count(cup, plate, arrangement)
        self.ui.cup_count.set_maximum(max(0, maximum))
        self.ui.cup_limit.setText(
            "Mit diesem Muster passen hoechstens " + str(maximum) + " Sauger auf die Platte."
        )
        self._update_spacing_hint(cup, plate, arrangement, maximum)

    def _update_spacing_hint(self, cup, plate, arrangement: str, maximum: int) -> None:
        """Was der eingestellte Saugerabstand kostet - in Saugern.

        Die haeufigste Frage an dieser Platte ist, warum die Sauger in der
        Zeichnung nicht aneinanderstossen. Die Antwort ist dieses Feld, und sie
        ueberzeugt erst mit der Zahl daneben: bei einer Platte 800 x 600 mit
        SPB2 30 kosten 10 mm Abstand 157 von 391 moeglichen Saugern.

        Die Vergleichszahl kommt aus derselben Verteilung wie die obere Grenze,
        nur mit Abstand null - gerechnet wird sie in der Engine, nicht hier
        (Spezifikation 37).
        """
        if plate.min_spacing_mm <= 0.0:
            self.ui.min_spacing_info.setText(
                "Die Sauger stossen mit ihrem Aussenmass aneinander - "
                "dichter laesst sich die Platte nicht bestuecken."
            )
            return

        touching = self._service.max_cup_count(
            cup, replace(plate, min_spacing_mm=0.0), arrangement
        )
        text = (
            "Lichter Abstand zwischen zwei Saugeraussenkanten. Das Rastermass ist "
            "Aussenmass " + format(cup.outer_diameter_mm, "g") + " mm plus dieser Wert."
        )
        if touching > maximum:
            text += (
                " Mit 0 mm stossen sie aneinander - dann passen "
                + str(touching) + " statt " + str(maximum) + " Sauger auf die Platte."
            )
        self.ui.min_spacing_info.setText(text)

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
        if self.ui.use_pallet_pattern.isChecked() and snapshot.pattern_id:
            pattern = self._context.settings.get_pattern(snapshot.pattern_id)
            if pattern is not None:
                pattern_id = pattern.strategy
                self.ui.package_info.setText(
                    "Anordnung nach Muster '" + pattern.name + "' aus der Palettierung."
                )
        if not pattern_id:
            self.ui.package_info.setText("Anordnung als gleichmaessiges Raster.")

        request = VacuumInput(
            package=package,
            plate=self._current_plate(),
            cup=cup,
            requested_cup_count=self.ui.cup_count.value(),
            package_count=self.ui.package_count.value(),
            pattern_id=pattern_id,
            arrangement_id=self._current_arrangement(),
            target_vacuum_pa=mbar_to_pa(self.ui.vacuum.value()),
            ambient_pa=self._defaults.ambient_pa,
            pump=replace(self._defaults.pump, nominal_flow_m3s=self.ui.flow.value() / 3600.0),
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
        self._service.calculate_async(request, snapshot.revision)

    def _on_started(self, _ticket) -> None:
        self.ui.calculate_button.setEnabled(False)
        # Das bisherige Ergebnis bleibt stehen, wird aber blass gezeichnet:
        # es gilt schon nicht mehr, ist aber besser als eine leere Flaeche.
        self.ui.view.set_stale(True)

    def _on_result(self, result: VacuumResult) -> None:
        self.ui.calculate_button.setEnabled(True)
        self._result = result
        self._result_revision = result.meta.state_revision
        self._needs_recalculation = False
        self.ui.banner.hide_message()
        self.ui.view.set_result(result)
        self._show_result(result)

    def _on_failed(self, message: str) -> None:
        self.ui.calculate_button.setEnabled(True)
        self.ui.results.clear_values()
        self.ui.flow_results.clear_values()
        self.ui.banner.show_message(message)

    # Anzeige ------------------------------------------------------------------

    def _show_result(self, result: VacuumResult) -> None:
        grid = self.ui.results
        grid.set_value("status", result.status.label, _STATUS_COLORS.get(result.status, ""))
        grid.set_value("max_mass", format(result.max_package_mass_kg, ".2f") + " kg")
        grid.set_value("actual_mass", format(result.actual_mass_kg, ".2f") + " kg")
        grid.set_value(
            "needed_cups",
            str(result.required_cup_count) + " von " + str(result.sealed_count) + " wirksamen",
            PALETTE.error if result.required_cup_count > result.sealed_count else "",
        )

        grid.set_value("arrangement", self.ui.arrangement_box.currentText())
        grid.set_value("cups_total", str(result.total_cup_count) + " von max. " + str(result.max_cup_count))
        grid.set_value("cups_sealed", str(result.sealed_count), PALETTE.ok if result.sealed_count else PALETTE.error)
        grid.set_value("cups_partial", str(result.partial_count),
                       PALETTE.warning if result.partial_count else "")
        grid.set_value("cups_open", str(result.open_count), PALETTE.error if result.open_count else "")
        grid.set_value("area", format(result.effective_area_mm2 / 100.0, ".1f") + " cm2")

        grid.set_value("packages", str(len(result.package_rects)))

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
        Klick auf "Berechnen" wartet, obwohl alle Eingaben vorliegen, ist eine
        ueberfluessige Huerde.
        """
        if self._result is None or self._needs_recalculation or self._is_stale():
            self.calculate()

    def commit_now(self) -> None:
        self._debouncer.flush()

    def shutdown(self) -> None:
        window_state.save_splitter(self.ui.splitter, SETTINGS_SECTION)
        self._debouncer.cancel()
        self._service.cancel()


class VacuumModule:
    """Anmeldung des Moduls (Spezifikation 06)."""

    module_id = MODULE_ID
    title = "Vakuumplatte"
    order = 20

    def create_widget(self, context: AppContext) -> QWidget:
        return VacuumTab(context)
