# Berechnungen

Modular erweiterbare Sammlung technischer Berechnungsprogramme für Windows,
Python 3.11+ mit PyQt6.

Zwei Module in dieser Fassung:

| Tab | Aufgabe |
|---|---|
| **Palettierung** | Optimale Anordnung auf verschiedenen Palettentypen und Palettiermustern, 2D- und 3D-Ansicht |
| **Vakuumplatte** | Saugerplatte zum Anheben: Saugerverteilung, wirksame und offene Sauger, Leckage, Haltekraft, maximales Paketgewicht |

Die **Paketdaten** — Maße, Gewicht und zulässige Stapellast — stehen am Kopf der
Palettierung, über der Palettenauswahl. Sie sind kein eigener Tab, sondern die
gemeinsame Eingabe beider Module: sie gelten für die ganze Anwendung, und eine
Änderung rechnet beide Ergebnisse neu.

---

## Starten

```bash
python -m app                 # Anwendung starten
python -m app --check         # nur Startsequenz prüfen, ohne Oberfläche
python -m app --json          # Statusbericht als JSON
python -m app --config PFAD   # anderes Konfigurationsverzeichnis
```

`main.py` ist der Einstiegspunkt der gepackten Fassung — für die Arbeit am
Quelltext ist `python -m app` der Weg.

## Installation

```bash
pip install PyQt6                    # Pflicht
pip install pyvista pyvistaqt        # 3D-Ansicht (optional)
pip install ortools                  # zusätzliche Löser-Strategie (optional)
pip install pytest pytest-qt         # Tests
```

Fehlt eine optionale Abhängigkeit, läuft die Anwendung vollständig weiter: die
3D-Ansicht zeigt einen Hinweis, die Löser-Option wird ausgegraut.

> **Hinweis zu PySide6:** Liegt PySide6 parallel installiert vor, lädt `qtpy`
> dessen Qt-DLLs und der anschließende PyQt6-Import scheitert. `pytest.ini`
> legt deshalb `qt_api = pyqt6` fest.

## Tests

```bash
python -m pytest              # alle 550 Tests, rund 13 Sekunden
python -m pytest tests/test_architecture.py   # nur die Schichtregeln
python -m pytest tests/test_ui_files.py       # nur die Layoutdateien
```

---

## Oberfläche bearbeiten (.ui-Dateien)

Die Anordnung jedes Tabs steht in einer eigenen Layoutdatei und lässt sich im
**Qt Designer** grafisch bearbeiten. Dasselbe gilt für das Paketformular
(`app/gui/package/package_form.ui`), das kein Tab ist, aber denselben Weg geht:

```
app/gui/vacuum/vacuum_tab.ui        Anordnung, Gruppen, Beschriftungen
   │   python tools/build_ui.py     (pyuic6)
   ▼
app/gui/vacuum/ui_vacuum_tab.py     erzeugt — nicht von Hand ändern
   │
   ▼
app/gui/vacuum/vacuum_tab.py        Ereignisse, Berechnung, Zustand,
                                    Service, Ergebnisanzeige
```

```bash
pyqt6-tools designer app/gui/vacuum/vacuum_tab.ui   # bearbeiten
python tools/build_ui.py                            # übersetzen
python tools/build_ui.py --check                    # nur prüfen
```

`AUTOBUILD.py` übersetzt vor dem Paketieren selbst — im Paket liegen nur die
erzeugten Python-Dateien. `tests/test_ui_files.py` übersetzt bei jedem Testlauf
neu und vergleicht mit der eingecheckten Datei; eine vergessene Übersetzung
fällt damit sofort auf und nicht erst am alten Layout im laufenden Programm.

### Was gehört wohin

| | Layoutdatei (`.ui`) | Quelltext (`.py`) |
|---|---|---|
| Anordnung, Gruppen, Reihenfolge | ✔ | |
| Beschriftungen, Tooltips, Größenrichtlinien | ✔ | |
| Wertebereiche, Einheiten, Schrittweiten | | ✔ |
| Zeilen der Ergebnisanzeige | | ✔ |
| Ereignisse, Berechnung, Zustand | | ✔ |
| Farben (über `role`-Eigenschaft) | Rolle | Farbe (`app/gui/theme.py`) |

Dass eine Länge in Millimetern angegeben wird und höchstens 5000 betragen darf,
ist Fachwissen und keine Gestaltung — in der XML-Datei läge es als namenlose
Eigenschaft ohne jede Prüfung. Umgekehrt hat eine Farbangabe im Designer nichts
verloren: die Layoutdatei setzt nur `role="note"`, das Aussehen steht einmal im
Stylesheet.

Zwei Fallstricke, die `tools/build_ui.py` und `tests/test_ui_files.py`
abfangen, weil sie erst im fertigen Fenster auffallen: die Eigenschaft
`stretch` an einem Layout (pyuic6 erzeugt daraus einen ungültigen Aufruf —
stattdessen Größenrichtlinien verwenden) und ein umbrechender Hinweistext ohne
Mindestbreite (Qt schätzt die Höhe dann für eine Breite von einem Bildpunkt und
reißt fingerbreite Lücken ins Formular).

---

## Konfiguration

Alle technischen Daten stehen in `config/` und werden nur gelesen. Änderungen
übernimmt die Anwendung über **Datei → Konfiguration neu laden** (F5), ohne
Neustart.

| Datei | Inhalt |
|---|---|
| `pallets.json` | Palettentypen: Maße, zulässige Last und Höhe, Überstand |
| `pallet_patterns.json` | Palettiermuster: Ebenenstrategie und Z-Modus |
| `suction_cups.json` | Saugertypen mit Datenblattwerten (24 Stück, vier Schmalz-Baureihen) |
| `vacuum_defaults.json` | Vorgaben und Modellparameter der Vakuumrechnung |

Ein fehlerhafter Eintrag kostet diesen Eintrag, nicht die Datei: die übrigen
bleiben nutzbar, die Beanstandung steht in der Problemliste. Ist eine Datei
unbrauchbar, springen eingebaute Mindestdaten ein — die Anwendung bleibt
bedienbar, gerade dann, wenn man den Fehler ansehen möchte.

### Mitgelieferte Saugertypen

| Baureihe | Falten | Größen | Bemerkung |
|---|---|---|---|
| SPB1 | 1,5 | 10…80 | mit Abreiß- und Querkraft |
| SPB2 | 2,5 | 20…50 | mit Abreiß- und Querkraft |
| SPB2f | 2,5 | 15…50 | flache Bauform, keine Abreißkraft im Datenblatt |
| SPB4 | 4,5 | 20…50 | großer Hub, keine Abreißkraft bei −0,6 bar |

Der Abgleich der Datenblattkraft gegen die Kreisfläche des Faltendurchmessers d2
geht **nur bei SPB2** auf (unter 1 % Abweichung). Bei SPB1 liegt er rund 10 %
daneben, bei SPB4 zwischen +7 und −15 %, bei SPB2f 30–50 um bis zu −81 % — dort
ist d2 konstruktiv gar nicht die kraftübertragende Fläche. Das ist unkritisch:
gerechnet wird ausschließlich mit der Datenblattkraft (`F / Δp_ref`), d2 dient
nur als Gegenprobe und geht in kein Ergebnis ein. Der Befund steht im
Rechenweg.

### Ein neuer Saugertyp

Eintrag in `config/suction_cups.json` ergänzen. Pflichtangaben aus dem
Datenblatt des Herstellers:

```json
{
  "id": "spb2_30",
  "name": "SPB2 30",
  "nominal_diameter_mm": 30,
  "effective_diameter_mm": 16.9,      // d2, innerer Faltendurchmesser
  "sealing_lip_diameter_mm": 31.4,    // Ds, entscheidet über die Dichtheit
  "outer_diameter_mm": 34.0,          // Dmax(S), bestimmt den Rasterabstand
  "bore_diameter_mm": 4.0,            // dn, bestimmt die Fremdluft
  "theoretical_force_n": 14.4,
  "reference_vacuum_mbar": 600
}
```

### Ein neues Palettiermuster

Eintrag in `config/pallet_patterns.json`, sofern die Strategie in
`app/engines/patterns/strategies.py` angemeldet ist. Verfügbar sind `auto`,
`max_count`, `uniform_grid`, `guillotine_mix`, `running_bond`, `checkerboard`,
`pinwheel`, `spiral`, `perimeter`, `ring`, `column`.

**Kein Muster lässt Lücken zwischen den Paketen.** Ein Wechsel der Ausrichtung
von Paket zu Paket geht nur bei quadratischer Grundfläche ohne Lücke auf — ein
Paket 400 × 300 ist quer 400 mm hoch und längs 300 mm, nebeneinander im selben
Band blieben zwangsläufig 100 mm frei. Schachbrett, Windrad, Spirale und
Randverband wechseln deshalb bei rechteckigen Paketen **bandweise**: jedes Band
besteht aus vollen Reihen einer Ausrichtung. Bei quadratischen Paketen bleibt
der feldweise Wechsel erhalten. Einzige Ausnahme ist der Ringstapel, dessen
freier Kern die Definition des Musters ist.

---

## Ein neues Berechnungsmodul

Drei Schritte, ohne Eingriff in Hauptfenster oder Kernarchitektur:

```python
# 1. Layout anlegen (app/gui/<modul>/<modul>_tab.ui) und übersetzen,
#    dann das Widget bauen (app/gui/<modul>/<modul>_tab.py)
class MeinTab(TabHost):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.ui = Ui_MeinTab()
        self.ui.setupUi(self)
        ...  # context.state, context.settings, context.reporter, ...

# 2. Modulvertrag erfüllen
class MeinModul:
    module_id = "mein_modul"
    title = "Mein Modul"
    order = 40

    def create_widget(self, context: AppContext) -> QWidget:
        return MeinTab(context)

# 3. In app/gui/module_registry.py eintragen
def default_modules():
    return [PalletModule(), VacuumModule(), MeinModul()]
```

`tests/test_architecture.py` prüft, dass jedes registrierte Modul den Vertrag
erfüllt und dass das Hauptfenster kein Modul beim Namen nennt.
`tests/test_ui_files.py` prüft, dass zu jedem `*_tab.py` eine `*_tab.ui` gehört,
dass der Tab seine erzeugte Klasse als `self.ui` hält und dass er keine
Anordnung mehr im Quelltext baut.

---

## Bedienung

### Ergebnisse rechnen automatisch nach

Eine Änderung der Paketdaten erzeugt keine Meldung, sondern eine neue
Berechnung. Solange ein Tab verdeckt ist, wird die Änderung nur vorgemerkt und
beim Aufschlagen nachgeholt — Rechenzeit für Ergebnisse, die niemand ansieht,
wäre verschenkt. Wer oben im Paketformular Werte ändert und dann auf
*Vakuumplatte* klickt, sieht dort das Ergebnis zu den neuen Werten.

### Helle und dunkle Fenster

Steht Windows auf **dunkle Fenster** (Einstellungen → Personalisierung →
Farben → *App-Modus: Dunkel*), startet die Anwendung dunkel — Bedienelemente,
Menüs und die Zeichnungen gleichermaßen. Steht Windows auf hell, ändert sich
nichts.

Gelesen wird die Einstellung von Windows beim Start; ein Wechsel während des
Betriebs wirkt beim nächsten Start. Zum Ansehen der anderen Fassung genügt eine
Umgebungsvariable:

```bat
set TRXING_THEME=dark     :: immer dunkel
set TRXING_THEME=light    :: immer hell
set TRXING_THEME=auto     :: wie Windows (Vorgabe)
```

Die dunkle Fassung besteht aus drei Teilen: der Qt-Palette und den Farben der
Zeichnungen (`app/visualization/theme.py`), dem Qt-Stil *Fusion* — der einzige,
der eine eigene Palette vollständig durchreicht — und dem Stylesheet in
`app/gui/darkstyle/` für Rollbalken, Ankreuzfelder und Aufklapppfeile samt
ihrer Bildchen. Verdrahtet ist das in `app/gui/theme.py`.

### Programmsymbol

`app/gui/icons/pallet.ico` — eine Datei für zwei Zwecke: die Anwendung setzt sie
beim Start als Fenstersymbol (jedes Fenster und jeder Dialog erbt es), und
`AUTOBUILD.py` gibt sie PyInstaller als Symbol der fertigen `.exe` mit. Ein
Austausch betrifft deshalb nur diese eine Datei — gleicher Name, gleicher Ort,
und beide Wege stimmen wieder. Das Format ist Absicht: eine `.ico` trägt 16 bis
512 Bildpunkte in sich, Windows greift sich die passende Größe.

### Größen und Aufteilung einstellen

Das meiste stellt man mit der Maus ein — die Anwendung merkt es sich beim
Schließen und stellt es beim nächsten Start wieder her:

| Was | Wie | Gemerkt in |
|---|---|---|
| Fenstergröße und -lage | Fenster ziehen | `HKCU\Software\TRXing\MainWindow` |
| Aufteilung Bedienspalte / Zeichenfläche | Griff zwischen beiden ziehen | `…\PalletTab`, `…\VacuumTab` |
| Zuletzt benutzter Tab | anklicken | `…\MainWindow` |

Die Vorgaben für den allerersten Start stehen im Quelltext, jede an genau einer
Stelle:

| Einstellung | Datei | Konstante |
|---|---|---|
| **Schriftgröße aller Bedienelemente** | `app/gui/theme.py` | `FONT_SIZE_OFFSET_PT` |
| **Fenstergröße beim ersten Start** | `app/gui/main_window.py` | `DEFAULT_SIZE` |
| Aufteilung Palettierung | `app/gui/pallet/pallet_tab.py` | `SPLITTER_SIZES` |
| Aufteilung Vakuumplatte | `app/gui/vacuum/vacuum_tab.py` | `SPLITTER_SIZES` |

`FONT_SIZE_OFFSET_PT` ist die Schriftgröße in Punkten **gegenüber der
Windows-Vorgabe**: `0` übernimmt sie, `-1` macht die ganze Oberfläche
kompakter, `2` deutlich größer. Die Schrift bestimmt fast alles Übrige mit —
Zeilenhöhen, Eingabefelder, Knöpfe und Rahmen richten sich nach ihr, eine
einzelne Größe muss dafür nirgends nachgezogen werden.

> **Eine geänderte Vorgabe wirkt erst, wenn der gemerkte Wert weg ist.** Wer
> `DEFAULT_SIZE` ändert und nichts passieren sieht, löscht den Wert `geometry`
> unter `HKCU\Software\TRXing\MainWindow` — danach gilt wieder der Quelltext.
> Dasselbe gilt für die Aufteilung (`splitter`).

### Saugermuster

Im Vakuumtab legt das Auswahlfeld **Saugermuster** fest, wie die Sauger auf der
Platte sitzen:

| Muster | Anzahl (800 × 600 mm, SPB2 30) |
|---|---|
| Raster, gleichmäßig verteilt | 234 |
| Raster, dicht an dicht | 234 |
| **Dichteste Packung (maximale Anzahl)** | **263** |
| Nur am Rand | 58 |
| Nur über den Paketen | je nach Belegung |

Die dichteste Packung nutzt versetzte Reihen im Dreiecksgitter — gleich große
Kreise lassen sich so bis 90,7 % statt 78,5 % der Fläche packen, das sind rund
15 % mehr Sauger und damit die größte erreichbare Auflage- und Wirkfläche.

*Nur über den Paketen* ist der Fall für eine Platte, die für ein bekanntes
Produkt gebaut wird: unbelegte Positionen entfallen ganz, und der
Fremdluftbedarf geht auf null.

### Wie viele Sauger auf die Platte passen

Den größten Hebel hat **nicht** das Muster, sondern das Feld **Saugerabstand**:
das lichte Maß zwischen zwei Saugeraußenkanten. Das Rastermaß ist Außenmaß
*plus* Saugerabstand — bei einem SPB2 30 also 34,0 mm + Abstand. Das Feld sagt
unter sich selbst, was der eingestellte Wert kostet: „Mit 0 mm stoßen sie
aneinander — dann passen 391 statt 234 Sauger auf die Platte.".

| Saugerabstand | Raster, dicht an dicht | Dichteste Packung |
|---|---|---|
| 10 mm (Vorgabe) | 234 | 263 |
| 0 mm | **391** | **428** |

Bei 0 mm stoßen die Außenmaße direkt aneinander — die Legende der Draufsicht
schreibt das dann ausdrücklich dazu. Ob das zulässig ist, entscheidet der
Aufbau: Anschlussnippel, Schlauchführung und Montagewerkzeug brauchen
Zwischenraum. Die Vorgabe von 10 mm steht in
`config/vacuum_defaults.json` unter `plate.min_spacing_mm` und lässt sich im
Feld *Saugerabstand* jederzeit überschreiben.

Das Muster verteilt nur, was das Rastermaß übriglässt: *gleichmäßig verteilt*
zieht die Sauger über die ganze Platte auseinander, *dicht an dicht* zieht
dieselbe Anzahl in die Mitte zusammen, und die *dichteste Packung* gewinnt
durch versetzte Reihen rund 15 % mehr Plätze.

### Die Platte darf kleiner sein als das Paket

Eine Saugerplatte greift in die Mitte der Lage; die äußeren Kartons ragen
darüber hinaus. Die Plattengröße begrenzt deshalb nur, wo Sauger sitzen können
— nicht, wie die Pakete liegen. Wie viele Pakete überstehen, steht in den
Warnungen.

Die Anordnung wächst dabei **von innen nach außen und waagerecht**: zuerst
füllt sich die Fläche unter der Platte, danach legen sich weitere Pakete
seitlich an, nicht darüber und darunter. Auf einer Platte für 2 × 2 Pakete
entstehen so 3 × 2 und 4 × 2. Gemessen wird der Abstand zur Plattenmitte in
Rasterzellen statt in Millimetern — sonst entschiede das Seitenverhältnis des
Kartons über die Richtung, und ein Paket 400 × 300 baute einen hohen schmalen
Stapel auf.

### Rechenwege und Formeln

**Hilfe → Rechenwege und Formeln** (F1) öffnet eine Dokumentation, die jede
Berechnung der Anwendung erklärt: mathematisch, mit Zahlenbeispielen und mit
Verweis auf die Datei, in der die Formel steht. Sieben Kapitel, durchsuchbar,
nicht modal — man liest sie neben dem Tab, um den es geht.

---

## Zu den physikalischen Ergebnissen

Die Anwendung gibt keine scheinbar exakten Zahlen aus frei erfundenen
Parametern aus. Jeder Wert der Vakuumrechnung trägt seine Herkunft, und die
Oberfläche zeigt sie im Abschnitt **Annahmen**:

* **Datenblatt** — vom Hersteller angegeben (Saugkraft, Abreißkraft, Geometrie)
* **Konfiguration** — Benutzer- oder Anlagenangabe (Permeabilität,
  Sicherheitsfaktor, Strombegrenzer)
* **Modellannahme** — Annahme des Rechenmodells (Ausflussbeiwert,
  Pumpenkennlinie ohne Stützpunkte)

Die theoretischen Saugkräfte des Datenblatts gelten bei glatter, trockener
Oberfläche und enthalten ausdrücklich **keinen Sicherheitsfaktor**; er wird
gesondert angesetzt.

**Zwei Punkte, die in der Praxis über das Ergebnis entscheiden:**

Ein ungedrosselter offener Sauger zieht bei −0,6 bar rund 7 m³/h (SPB2 20–30)
bzw. 17 m³/h (SPB2 40/50) Fremdluft. Wenige offene Sauger können das Vakuum der
ganzen Platte zusammenbrechen lassen. Die Software rechnet deshalb den
Arbeitspunkt, statt das Sollvakuum anzunehmen.

Ein Sauger dichtet nur, wenn sein **Dichtlippenring vollständig** auf der
Kartonfläche liegt. Ein zu 95 % aufliegender Sauger trägt nichts — er leckt wie
ein offener. Gezählt wird nicht nach Mittelpunkt, sondern geometrisch.

---

## Weiteres

* Architektur, Schichtregeln und Leistungsentscheidungen: [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)
* Die ursprüngliche Aufgabenstellung: `doc/01.txt` bis `doc/03.txt`
* Protokoll: `%LOCALAPPDATA%\TRXing\logs\app.log` (rotierend, 3 Sicherungen)
# TRXing
# TRXing
