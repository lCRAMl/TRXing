"""Die Paketdaten - Quelle der Wahrheit fuer jede Berechnung der Anwendung.

Frueher ein eigener Tab, jetzt ein Formular am Kopf der Palettierung. Der Grund
ist der Arbeitsablauf: die Paketmasse sind die erste Eingabe jeder Rechnung,
und wer sie aendert, will die Wirkung sofort sehen. Ein eigener Tab bedeutete,
dass man fuer jede Korrektur hin und her wechselt.

Fachlich aendert der Umzug nichts. Das Formular liest Eingaben, baut daraus ein
PackageSpec und uebergibt es dem PackageService; von dort erreicht es ueber den
Anwendungszustand jeden Tab. Es prueft nichts selbst und rechnet nichts ausser
dem, was direkt danebensteht - Volumen und Dichte sind abgeleitete
Eigenschaften des DTO, keine Fachlogik.

    package_form.ui   Anordnung, Gruppen, Beschriftungen, Groessenrichtlinien
    package_form.py   Wertebereiche, Ereignisse, Validierung, Anzeige

Die Wertebereiche stehen bewusst hier und nicht in der XML-Datei: dass eine
Laenge in Millimetern angegeben wird und hoechstens 5000 betragen darf, ist
Fachwissen und keine Gestaltung.

Uebernommen wird entprellt: wer eine Breite von 300 auf 3000 aendert, tippt
kurzzeitig 30 und 300 - jede Zwischenstufe sofort in den Zustand zu schreiben
wuerde je eine Palettier- und eine Vakuumrechnung ausloesen, die nie jemand
sehen will (Spezifikation 32).

Das Formular ist kein Tab und kennt keinen. Es haengt in dem Widget, das es
aufnimmt; dessen Tab reicht ihm die drei Lebenszeichen weiter, die es braucht:
on_state_changed, commit_now und shutdown.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from app.dto.package import PackageSpec
from app.gui.common.widgets import Debouncer
from app.gui.package.ui_package_form import Ui_PackageForm
from app.services.app_state import AppStateSnapshot, StateChange
from app.services.context import AppContext


class PackageForm(QWidget):
    """Eingabemaske des aktuellen Pakets."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._service = context.packages
        self._debouncer = Debouncer(self._commit, context.debounce_ms, self)

        # Zusammensetzung statt Vererbung: die aus der Layoutdatei erzeugten
        # Namen liegen unter self.ui und koennen weder mit denen von QWidget
        # noch mit eigenen kollidieren. Beim Lesen ist zudem sofort erkennbar,
        # was aus dem Designer stammt.
        self.ui = Ui_PackageForm()
        self.ui.setupUi(self)

        self._configure_fields()
        self._build_result_rows()
        self._connect()

        self._load_from_state()
        self._refresh()
        # Die angezeigten Vorgabewerte sofort uebernehmen. Ohne das steht beim
        # Start ein gueltiges Paket auf dem Bildschirm, waehrend der Zustand
        # leer ist - die Palettierung meldet dann "keine Paketdaten", obwohl
        # welche dastehen, und der Benutzer muss erst ein Feld antippen.
        self._commit()

    # Aufbau -------------------------------------------------------------------

    def _configure_fields(self) -> None:
        """Wertebereiche und Einheiten der Eingabefelder.

        Die Grenzen fangen Tippfehler und Einheitenverwechslungen ab, nicht den
        Anwendungsbereich: 5000 mm Kantenlaenge und 2000 kg sind grosszuegig,
        aber eine Laenge von 400000 ist eine Eingabe in Mikrometern.
        """
        self.ui.length.configure("mm", minimum=0.0, maximum=5000.0, decimals=1, step=10.0, value=400.0)
        self.ui.width.configure("mm", minimum=0.0, maximum=5000.0, decimals=1, step=10.0, value=300.0)
        self.ui.height.configure("mm", minimum=0.0, maximum=5000.0, decimals=1, step=10.0, value=200.0)
        self.ui.weight.configure("kg", minimum=0.0, maximum=2000.0, decimals=3, step=0.5, value=5.0)
        self.ui.stack_load.configure("kg", minimum=0.0, maximum=20000.0, decimals=1, step=5.0, value=0.0)

    def _build_result_rows(self) -> None:
        """Die Zeilen der Ergebnisanzeige.

        Sie stehen hier und nicht in der Layoutdatei: es sind Daten, keine
        Anordnung. Der Designer bestimmt, wo das Feld sitzt und wie es heisst.
        """
        grid = self.ui.derived
        grid.add_row("volume", "Volumen", "-")
        grid.add_row("footprint", "Grundflaeche", "-")
        grid.add_row("density", "Dichte", "-")
        grid.add_row("layers", "Stapelbar", "-")

    def _connect(self) -> None:
        for field in self._fields().values():
            field.value_changed.connect(self._on_input_changed)
        self.ui.tipping.toggled.connect(self._on_input_changed)
        self.ui.label_field.textEdited.connect(self._on_input_changed)

    def _fields(self) -> dict:
        """Feldname im DTO -> Eingabefeld.

        Der Schluessel ist der technische Feldname des PackageSpec. Nur damit
        laesst sich eine Meldung der Validierung dem richtigen Widget zuordnen,
        ohne die Zuordnung ein zweites Mal aufzuschreiben.
        """
        return {
            "length_mm": self.ui.length,
            "width_mm": self.ui.width,
            "height_mm": self.ui.height,
            "weight_kg": self.ui.weight,
            "max_stack_load_kg": self.ui.stack_load,
        }

    # Eingabe ------------------------------------------------------------------

    def _current_spec(self) -> PackageSpec:
        return PackageSpec(
            length_mm=self.ui.length.value(),
            width_mm=self.ui.width.value(),
            height_mm=self.ui.height.value(),
            weight_kg=self.ui.weight.value(),
            max_stack_load_kg=self.ui.stack_load.value(),
            allow_tipping=self.ui.tipping.isChecked(),
            label=self.ui.label_field.text().strip(),
        )

    def _on_input_changed(self, *_args) -> None:
        # Sofort pruefen und anzeigen, aber erst entprellt uebernehmen: der
        # Fehler am Feld soll beim Tippen erscheinen, die Neuberechnung der
        # Ergebnisse erst, wenn die Eingabe zur Ruhe gekommen ist.
        self._refresh()
        self._debouncer.trigger()

    def _commit(self) -> None:
        spec = self._current_spec()
        report = self._service.validate(spec)
        if report.ok:
            self._service.update_package(spec)
        else:
            # Ungueltige Eingabe: bisheriges Paket bleibt stehen, aber die
            # abhaengigen Anzeigen duerfen nicht so tun, als sei alles frisch.
            self._context.gate.invalidate("pallet")
            self._context.gate.invalidate("vacuum")

    # Lebenszeichen des aufnehmenden Tabs ---------------------------------------

    def commit_now(self) -> None:
        """Ausstehende Uebernahme sofort ausfuehren."""
        self._debouncer.flush()

    def on_state_changed(self, change: StateChange, snapshot: AppStateSnapshot) -> None:
        """Das Formular ist die Quelle der Paketaenderung und muss sie nicht
        zurueckgespiegelt bekommen. Nur wenn jemand anders das Paket setzt -
        etwa ein spaeteres Lademodul - zieht die Anzeige nach."""
        if change is StateChange.PACKAGE and snapshot.package != self._current_spec():
            self._load_from_state()
            self._refresh()

    def shutdown(self) -> None:
        self._debouncer.cancel()

    # Anzeige ------------------------------------------------------------------

    def _refresh(self) -> None:
        spec = self._current_spec()
        report = self._service.validate(spec)

        for name, widget in self._fields().items():
            issues = report.for_field(name)
            if not issues:
                widget.clear_message()
            elif any(issue.is_error for issue in issues):
                widget.set_error(next(issue.message for issue in issues if issue.is_error))
            else:
                widget.set_warning(issues[0].message)

        grid = self.ui.derived
        if not report.ok:
            grid.clear_values()
            return

        # Nur Liter. Frueher stand dasselbe Volumen zusaetzlich in
        # Kubikzentimetern darunter; im Band kostet jede Stelle Breite, und die
        # zweite Zeile trug dieselbe Zahl mit verschobenem Komma.
        grid.set_value("volume", format(spec.volume_l, ".2f") + " l")
        grid.set_value("footprint", format(spec.footprint_area_mm2 / 100.0, ".1f") + " cm2")
        grid.set_value("density", format(spec.density_kgm3, ".1f") + " kg/m3")

        if spec.has_stack_load_limit:
            # Wie viele Pakete duerfen ueber dem untersten stehen: die Auflast
            # des untersten ist (n-1) mal das Paketgewicht.
            bearable = int(spec.max_stack_load_kg // spec.weight_kg) if spec.weight_kg > 0 else 0
            grid.set_value("layers", str(bearable + 1) + " uebereinander")
        else:
            grid.set_value("layers", "unbegrenzt")

    def _load_from_state(self) -> None:
        package = self._context.state.snapshot().package
        if package is None:
            return
        self.ui.length.set_value(package.length_mm)
        self.ui.width.set_value(package.width_mm)
        self.ui.height.set_value(package.height_mm)
        self.ui.weight.set_value(package.weight_kg)
        self.ui.stack_load.set_value(package.max_stack_load_kg)
        self.ui.tipping.setChecked(package.allow_tipping)
        self.ui.label_field.setText(package.label)
