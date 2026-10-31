"""Tab 1 - Palettierung.

Der Tab liest Paketdaten, Auswahl und Grenzwerte, ruft den PalletService und
zeigt an, was zurueckkommt. Er kennt weder den Optimierer noch die
Musterstrategien, und er rechnet nichts - auch nicht die Flaechenausnutzung,
die steht im Ergebnis.

Am Kopf sitzt das Paketformular. Es ist kein Teil dieses Tabs, sondern ein
eigenes Widget mit eigener Layoutdatei (app/pallet/form.py): die
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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QScrollArea, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget
)

from app.gui.theme import ViewMode
from app.pallet.models import PalletResult, SharedLayer
from qt_controls_pyrs import (
    CompactButton, CompactDropdown, CompactRadioButton, StaleBanner,
    WideResultGrid, compact_combo
)
from app.gui.debounce import Debouncer
from app.gui.window_state import restore_splitter, save_splitter, store
from app.pallet.form import PackageForm
from app.tab_registry import TabHost
from app.gui.theme import PALETTE
from app.domain.state import AppStateSnapshot, StateChange
from app.context import AppContext
from app.pallet.scene_3d import create_scene
from app.pallet.renderer import Pallet2DView
from app.gui.form_builder import (
    Ganzzahl, Gruppe, Hinweis, Oberflaeche, Schalter, Wahl, Zahl, baue
)

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


#: Die Bedienspalte als Beschreibung.
#:
#: Wertebereiche und Einheiten stehen hier, weil sie Fachwissen sind und keine
#: Gestaltung: dass eine Hoehe in Millimetern angegeben wird und eine Null
#: "nimm den Wert der Palette" bedeutet, gehoert zur Sache. Frueher lagen
#: Beschriftung und Einheit in zwei verschiedenen Dateien.
BEDIENSPALTE = [
    Gruppe("Palettenauswahl", [
        [Wahl("pallet_box", "Palettentyp")],
        [Wahl("pattern_box", "Palettiermuster")],
        [Hinweis("", name="pattern_hint")],
    ], name="selection_box", oben=True),

    # Was zusammengehoert, steht nebeneinander: die beiden Obergrenzen der
    # Palette in einer Zeile, Spalt und Stueckzahl in der naechsten. Das halbiert
    # die Hoehe der Spalte, und beim Lesen gehoert ohnehin zusammen, was hier
    # nebeneinander steht.
    Gruppe("Grenzwerte", [
        [Zahl("max_height", "max. Hoehe", "mm", dict(
            min=0.0, max=10000.0, stellen=0, schritt=50.0,
            hinweis="0 uebernimmt den Wert des Palettentyps")),
         Zahl("max_load", "max. Last", "kg", dict(
            min=0.0, max=100000.0, stellen=0, schritt=50.0,
            hinweis="0 uebernimmt den Wert des Palettentyps"))],
        [Zahl("gap", "Spalt", "mm", dict(
            min=0.0, max=200.0, stellen=1, schritt=1.0,
            hinweis="Lichter Mindestabstand zwischen zwei Paketen")),
         Ganzzahl("desired", "Stueckzahl", "Stueck", dict(
            min=0, max=100000, wert=0, null_text="so viele wie moeglich"))],
        [Schalter("use_solver", "Zusaetzlichen Loeser verwenden (langsamer, oft dichter)")],
    ], name="limits_box", oben=True),

#: Keine Knopfzeile mehr.
#:
#: Gerechnet wird nach jeder Eingabe von selbst, entprellt. Ein Knopf
#: "Berechnen" war damit ein zweiter Weg zum gleichen Ergebnis - und einer,
#: der beim Hinsehen das Gegenteil behauptet: wer ihn sieht, haelt die Anzeige
#: fuer veraltet, bis er geklickt hat. Der Abbruch steht in der Statusleiste,
#: neben dem Fortschritt, den er abbricht (siehe app/gui/notifications.py).
]

#: Das Ergebnisraster steht NICHT in der Bedienspalte.
#:
#: Dort rollte es mit und war bei kleinem Fenster weggescrollt - ausgerechnet
#: das, worauf man nach dem Rechnen schaut. Es sitzt jetzt unter der Zeichnung
#: und bleibt stehen. Beide Tabs sind damit gleich gebaut: links Eingaben, die
#: rollen duerfen, rechts Zeichnung und Ergebnis, die immer dastehen.

#: Die Zeilen der Ergebnisanzeige. None ist eine Trennlinie.
ERGEBNISZEILEN = [
    ("total", "Pakete gesamt"),
    ("per_layer", "Pakete je Lage"),
    ("layers", "Anzahl Lagen"),
    None,
    ("weight", "Gesamtgewicht"),
    ("height", "Gesamthoehe mit Palette"),
    ("load_height", "Stapelhoehe"),
    None,
    ("utilization", "Flaechenausnutzung"),
    ("volume", "Raumausnutzung"),
    ("max_load", "Hoechste Paketbelastung"),
    ("limit", "Begrenzt durch"),
]


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

        # Die Namen liegen weiterhin unter self.ui - nur kommen sie jetzt aus
        # BEDIENSPALTE oben statt aus einer erzeugten Datei.
        self.ui = Oberflaeche()
        self._build_layout()

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

    def _build_layout(self) -> None:
        """Setzt das Fenster zusammen: Formularkopf, Band, Teiler.

        Der Formularteil kommt aus BEDIENSPALTE; was hier steht, ist die
        Umgebung - Teiler, Rollflaeche und Zeichenbereich. Das sind
        Einzelstuecke und keine Formularzeilen, deshalb von Hand.
        """
        self.ui.root = QVBoxLayout(self)
        self.ui.root.setContentsMargins(6, 6, 6, 6)
        self.ui.root.setSpacing(4)

        self.ui.package_host = QWidget()
        self.ui.package_layout = QVBoxLayout(self.ui.package_host)
        self.ui.package_layout.setContentsMargins(0, 0, 0, 0)
        self.ui.root.addWidget(self.ui.package_host)

        self.ui.banner = StaleBanner()
        self.ui.root.addWidget(self.ui.banner)

        self.ui.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.ui.root.addWidget(self.ui.splitter)

        # Links die Bedienspalte in einer Rollflaeche.
        self.ui.controls, self.ui = baue(BEDIENSPALTE, self.ui)
        self.ui.controls_scroll = QScrollArea()
        self.ui.controls_scroll.setWidgetResizable(True)
        self.ui.controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.ui.controls_scroll.setWidget(self.ui.controls)
        self.ui.splitter.addWidget(self.ui.controls_scroll)

        # Rechts die Zeichenflaeche mit ihrer Leiste.
        self.ui.view_panel = QWidget()
        self.ui.view_layout = QVBoxLayout(self.ui.view_panel)
        self.ui.view_layout.setContentsMargins(0, 0, 0, 0)
        self.ui.view_layout.setSpacing(4)

        self.ui.view_bar = QHBoxLayout()
        self.ui.view_bar.setSpacing(8)
        self.ui.button_2d = CompactRadioButton("2D Draufsicht")
        self.ui.button_2d.setChecked(True)   # die Draufsicht ist die Vorgabe
        self.ui.button_3d = CompactRadioButton("3D Ansicht")
        self.ui.layer_caption = QLabel("Ebene")
        self.ui.layer_box = CompactDropdown()
        self.ui.layer_box.setMinimumWidth(110)
        self.ui.reset_camera = CompactButton("Ansicht zuruecksetzen")
        # Erscheint erst mit der 3D-Ansicht - in der Draufsicht gibt es
        # keine Kamera zurueckzusetzen.
        self.ui.reset_camera.setVisible(False)
        for widget in (self.ui.button_2d, self.ui.button_3d, self.ui.layer_caption,
                       self.ui.layer_box, self.ui.reset_camera):
            self.ui.view_bar.addWidget(widget)
        self.ui.view_bar.addStretch(1)
        self.ui.view_layout.addLayout(self.ui.view_bar)

        self.ui.views = QStackedWidget()
        self.ui.view_2d = Pallet2DView()
        self.ui.scene_host = QWidget()
        self.ui.scene_layout = QVBoxLayout(self.ui.scene_host)
        self.ui.scene_layout.setContentsMargins(0, 0, 0, 0)
        self.ui.views.addWidget(self.ui.view_2d)
        self.ui.views.addWidget(self.ui.scene_host)
        self.ui.view_layout.addWidget(self.ui.views, 1)

        # Das Ergebnis unter der Zeichnung, ausserhalb der Rollflaeche: es
        # bleibt stehen, auch wenn die Eingaben nach unten weglaufen.
        self.ui.results = WideResultGrid("Ergebnis")
        self.ui.view_layout.addWidget(self.ui.results)

        self.ui.splitter.addWidget(self.ui.view_panel)

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
        restore_splitter(self.ui.splitter, SETTINGS_SECTION, SPLITTER_SIZES)

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
        """Was sich nicht beschreiben laesst: die Verfuegbarkeit des Loesers.

        Grenzen und Einheiten stehen in BEDIENSPALTE. Ob ortools installiert
        ist, weiss erst die laufende Anwendung.
        """
        available = self._service.solver_available()
        self.ui.use_solver.setEnabled(available)
        self.ui.use_solver.setToolTip(
            "Sucht die dichteste Lage mit einem Constraint-Loeser. Deterministisch "
            "eingestellt, dafuer langsamer als die Heuristik."
            if available else
            "Nicht verfuegbar - das Paket ortools ist nicht installiert."
        )

    def _build_result_rows(self) -> None:
        """Die Zeilen der Ergebnisanzeige, aus ERGEBNISZEILEN."""
        grid = self.ui.results
        for eintrag in ERGEBNISZEILEN:
            if eintrag is None:
                grid.add_separator()
            else:
                grid.add_row(*eintrag)

    def _connect(self) -> None:
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
        # Waehrend gerechnet wird, wird das bisherige Ergebnis blass gezeichnet -
        # es steht noch da, gilt aber schon nicht mehr.
        self.ui.view_2d.set_stale(True)
        if self._scene is not None:
            self._scene.set_stale(True)

    def _on_result(self, result: PalletResult) -> None:
        self._result = result
        self._result_revision = result.meta.state_revision
        self._needs_recalculation = False
        self.ui.banner.hide_message()
        self._show_result(result)

    def _on_failed(self, message: str) -> None:
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
        self._publish_layer()

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
        self._publish_layer()

    def _publish_layer(self) -> None:
        """Stellt die gerade angezeigte Lage fuer die Vakuumplatte bereit.

        Bewusst die ANGEZEIGTE und nicht immer die erste: bei Kreuz-, Laeufer-
        und Windradverband unterscheiden sich die Ebenen, und greifen will der
        Benutzer die, die er gerade vor sich sieht.

        Ohne Ergebnis wird None gemeldet. Der Vakuumtab faellt dann auf sein
        eigenes Raster zurueck, statt eine veraltete Lage weiterzuverwenden.
        """
        result = self._result
        if result is None or not result.layers:
            self._context.pallets.publish_layer(None)
            return

        index = self.ui.layer_box.currentData()
        index = int(index) if index is not None else 0
        layer = next((lay for lay in result.layers if lay.index == index), result.layers[0])
        pattern = self._current_pattern()
        self._context.pallets.publish_layer(
            SharedLayer.from_layer(
                layer,
                pattern_name=pattern.name if pattern is not None else "",
                state_revision=result.meta.state_revision,
            )
        )

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
        """Ohne Paketdaten gibt es nichts zu rechnen - das muss dastehen.

        Frueher wurde zusaetzlich der Knopf "Berechnen" gesperrt. Den gibt es
        nicht mehr, und das Band sagt deutlicher, WARUM nichts passiert, als
        ein grauer Knopf es konnte.
        """
        if self._context.state.snapshot().package is None:
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

        # Die bereitgestellte Lage gehoert zum alten Eingabestand und stimmt ab
        # hier nicht mehr. Sie wird zurueckgezogen statt weitergereicht: die
        # Vakuumplatte zeigt dann ihr eigenes Raster, was sichtbar etwas
        # anderes ist - waehrend eine stehengebliebene Lage aussaehe wie ein
        # gueltiges Ergebnis und zu einem falschen Paket gehoerte.
        #
        # Nur die Aenderungen, die den Palettenkanal entwerten - Paket, Palette,
        # Muster. Die Plattenmasse des Vakuumtabs stehen nicht darunter und
        # lassen die Lage deshalb in Ruhe.
        self._context.pallets.publish_layer(None)

        if snapshot.package is None:
            return

        self._needs_recalculation = True
        if self.isVisible():
            self._debouncer.trigger()

    def on_activated(self) -> None:
        """Beim Aufschlagen rechnen, wenn das Angezeigte nicht mehr stimmt.

        Auch beim allerersten Aufschlagen: ein leerer Tab, der auf eine
        Handlung wartet, obwohl alle Eingaben vorliegen, ist eine
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
        save_splitter(self.ui.splitter, SETTINGS_SECTION)
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
