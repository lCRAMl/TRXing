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
python -m pytest              # alle 557 Tests, rund 30 Sekunden
python -m pytest tests/test_architecture.py   # nur die Schichtregeln
python -m pytest tests/test_formularbau.py    # nur den Formularbau
```

---

## Wo liegt was

```
app/                 __main__ . start . tabs . kontext    das Programm

  palette/           Palettierung: Lagen legen, stapeln   ] senkrecht
  vakuum/            Saugplatte: verteilen, Kraft rechnen ]  geschnitten

  oberflaeche/       Farben, Formularbau, Meldungen,
                     Hilfe, Fensterzustand, Entprellung,  ]
                     hilfetexte/, darkstyle/, icons/      ]
  fach/              Paket, Einheiten, Geometrie, Muster, ] waagerecht
                     Katalog, Ergebnis, Zustand           ]  darunter
  technik/           Hintergrundarbeit, Protokoll, Pfade  ]

config/              die JSON-Kataloge, mitausgeliefert
doc/ARCHITECTURE.md  warum es so geschnitten ist
```

Die drei unteren Lagen tragen **keinen Gegenstand**: Werkzeugkasten,
Gemeinbesitz, Unterbau. Eine dritte Scheibe waere `app/<name>/` plus eine
Zeile in `app/tabs.py` - mehr nicht.

Beide Scheiben haben **dieselben Dateinamen**: `daten`, `rechnung`,
`zeichnung`, `tab`, `dienst`. Was ein Modul darf, sagt sein Name und nicht
sein Ordner - eine `rechnung.py` ist in jeder Scheibe eine `rechnung.py`.
Die Regeln stehen maschinenlesbar in `tests/test_architecture.py` und laufen
bei jedem Testlauf mit; der Hintergrund in
[doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

---

## Oberfläche bearbeiten (Beschreibungen)

Die Anordnung jedes Tabs steht als **Beschreibung im Quelltext** — eine Liste
von Zeilen, aus der `app/oberflaeche/formularbau.py` die Bedienelemente baut:

```python
BEDIENSPALTE = [
    Gruppe("Platte und Sauger", [
        [Wahl("cup_box", "Sauger-Typ")],
        [Hinweis("", name="cup_info")],
        [Zahl("plate_length", "Plattenlaenge", "mm",
              dict(min=10.0, max=3000.0, stellen=0, schritt=10.0))],
    ], name="plate_box"),
]
```

Eine Zeile hier ist eine Zeile auf dem Schirm; vier Felder nebeneinander sind
vier Einträge in einer Liste. Die Namen liegen danach unter `self.ui` —
`self.ui.plate_length` — wie zuvor.

**Warum nicht mehr der Qt Designer.** Bis Oktober 2026 lag die Anordnung in
`.ui`-Dateien, aus denen `pyuic6` Python erzeugte: 1054 Zeilen XML und 687
Zeilen erzeugter Quelltext. Der Designer konnte davon nichts zeigen, was
zählt — eigene Bedienelemente erscheinen dort als leere graue Kästen, weil er
hochgestufte Widgets als ihre Basisklasse zeichnet. Dazu war jede Formularzeile
geteilt: die Beschriftung in der XML, die Einheit und die Grenzen im Quelltext.
Wer die Einheit änderte, musste zwei Dateien anfassen.

### Die Bausteine

| Baustein | wird zu | wofür |
|---|---|---|
| `Zahl` | `CompactNumberField` | Maß mit Einheit und Platz für eine Meldung |
| `Ganzzahl` | `CompactIntField` | Stückzahl mit Einheit |
| `Wahl` | `CompactDropdown` | Auswahlfeld; gefüllt wird es vom Tab |
| `Text` | `CompactLineEdit` | einzeilige Eingabe |
| `Schalter` | `CompactCheckBox` | Kästchen, mit `angehakt` und `hinweis` |
| `Auswahlknopf` | `CompactRadioButton` | genau einer von mehreren |
| `Knopf` | `CompactButton` | mit `vorgabe`, `aktiv`, `sichtbar`; in den Tabs zurzeit nicht benutzt — gerechnet wird nach jeder Eingabe |
| `Hinweis` | `QLabel` (`role="note"`) | Erklärung unter einer Zeile |
| `Raster` | `CompactResultGrid` | Ergebniswerte; Zeilen trägt der Tab nach |
| `Platz` | `QWidget` | Platzhalter für Zeichenfläche oder 3D-Szene |
| `Gruppe` | `CompactGroupBox` | Rahmen mit Überschrift und Zeilen darin; `oben=True` setzt die Beschriftung über das Feld statt daneben |
| `Zeile` | `QHBoxLayout` | mehrere Elemente nebeneinander, ohne Rahmen |

### Das Gerüst beider Tabs

Beide Tabs sind gleich gebaut:

```
[Paketformular]          nur Palettierung, über die volle Breite
[Hinweisband]            erscheint nur bei veralteter Anzeige
[Teiler]
   links   Eingaben      scrollt, wenn es eng wird
   rechts  Zeichnung     bekommt allen Platz, der übrig ist
           Ergebnis      steht fest darunter
[Statusleiste]           Meldung · Tätigkeit · Fortschritt · Abbruch · Probleme
```

**Keine Knöpfe „Berechnen" und „Abbrechen" mehr.** Gerechnet wird nach jeder
Eingabe von selbst, entprellt; ein Knopf „Berechnen" war damit ein zweiter Weg
zum selben Ergebnis — und einer, der beim Hinsehen das Gegenteil behauptet: wer
ihn sieht, hält die Anzeige für veraltet, bis er geklickt hat. Der Abbruch
blieb nötig (ein Lauf mit dem zusätzlichen Löser kann lange dauern) und steht
jetzt in der Statusleiste, neben dem Fortschritt, den er abbricht — sichtbar
nur, solange etwas läuft.

Das Ergebnis steht **außerhalb** der Rollfläche. In der Bedienspalte rollte es
mit und war bei kleinem Fenster weggescrollt — ausgerechnet das, worauf man
nach dem Rechnen schaut.

Die Beschriftung steht **über** dem Feld (`oben=True`). Daneben addieren sich
Beschriftung und Feld; stehen zwei Paare in einer Zeile, addieren sich vier
Breiten. Gemessen am Vakuumtab: 650 Pixel Mindestbreite, obwohl die Felder
selbst nur 104 messen. Übereinander zählt je Spalte das Größere statt der
Summe — 426 statt 650. Breite ist das knappe Gut, weil daneben die Zeichnung
steht; Höhe darf scrollen.

### Was gehört wohin

| | Beschreibung | Quelltext des Tabs |
|---|---|---|
| Anordnung, Gruppen, Reihenfolge | ✔ | |
| Beschriftungen, Einheiten, Tooltips | ✔ | |
| Wertebereiche, Schrittweiten, Vorgaben | ✔ | |
| Zeilen der Ergebnisanzeige | ✔ (als Liste) | |
| Teiler, Rollflächen, Zeichenfläche | | ✔ |
| Ereignisse, Berechnung, Zustand | | ✔ |
| Farben | Rolle (`role="note"`) | `app/oberflaeche/darstellung.py` |

Die Umgebung eines Tabs — Teiler, Rollfläche, Zeichenfläche, 3D-Szene — steht
weiterhin im Quelltext. Das sind Einzelstücke und keine Formularzeilen;
`app/oberflaeche/formularbau.py` baut Formulare, keine Fenster.

`tests/test_formularbau.py` vergleicht Beschreibung und Benutzung: jeder Name,
den ein Tab unter `self.ui` anspricht, muss auch gebaut werden. Ohne diese
Prüfung fällt ein vergessener Eintrag erst beim Öffnen des Tabs auf, weit weg
von der Ursache.

### Wo stelle ich was ein

Von der Absicht zur Datei. Jede Zeile hat **genau eine** Stelle:

| Ich will ändern … | Datei | Wo darin |
|---|---|---|
| Beschriftung, Einheit, Grenzen, Schrittweite, Vorgabewert, Tooltip eines Feldes | `app/palette/tab.py`, `app/vakuum/tab.py`, `app/palette/formular.py` | in `BEDIENSPALTE` / `FORMULAR` — alles steht in einer Zeile beieinander |
| Reihenfolge der Felder, was nebeneinander steht, Gruppenaufteilung | dieselben Dateien | die Listenstruktur; eine innere Liste ist eine Zeile auf dem Schirm |
| Beschriftung über statt neben dem Feld | dieselben Dateien | `Gruppe(…, oben=True)` |
| Welche Zeilen die Ergebnisanzeige hat | dieselben Dateien | `ERGEBNISZEILEN`, `STROMZEILEN`, `ABGELEITET`; `None` ist eine Trennlinie |
| Einen neuen Feldtyp (es gibt noch keinen Baustein dafür) | `app/oberflaeche/formularbau.py` | eine Datenklasse und ein Zweig in `_zelle()` |
| Teiler, Rollfläche, Zeichenfläche, 3D-Szene, Ansichtsleiste | `app/palette/tab.py`, `app/vakuum/tab.py` | `_build_layout()` |
| **Größe der Bedienelemente** — Höhe einer Leiste, Luftrand, Textabstand innen | `qt_controls_pyrs/compact.py` | `COMPACT_HEIGHT`, `COMPACT_ROOM`, `COMPACT_PAD` |
| **Abstand zweier Formularzeilen** (senkrecht) | `qt_controls_pyrs/compact.py`, gelesen in `app/oberflaeche/formularbau.py` | `COMPACT_SPACING` |
| **Abstand Beschriftung ↔ Feld** und zwischen zwei Feldern einer Zeile | dieselbe Datei | `COMPACT_SPACING_X` |
| **Abstand zweier Gruppenrahmen** | dieselbe Datei | `COMPACT_GROUP_SPACING` |
| Rand und Abstand um die gesamte Tabfläche | `app/vakuum/tab.py`, `app/palette/tab.py` | `_build_layout()` — `root.setContentsMargins(6,6,6,6)`, `root.setSpacing(4)` |
| Breite der Bedienspalte beim ersten Start | `app/vakuum/tab.py`, `app/palette/tab.py` | `SPLITTER_SIZES` — danach gilt, wohin der Benutzer den Griff zieht |
| Wie schmal sich die Bedienspalte ziehen lässt | `app/vakuum/tab.py`, `app/palette/tab.py` | `_configure_layout()` — ergibt sich aus dem breitesten Inhalt |
| Maße eines einzelnen Elementtyps (Pfeilspalte, Kästchengröße) | `qt_controls_pyrs/compact.py` | die Konstanten der jeweiligen `Compact…`-Klasse |
| Spaltenzahl einer Ergebnisanzeige | dort, wo sie gebaut wird — z. B. `EinspaltigesRaster` in `app/vakuum/tab.py` | `COLUMNS` in einer eigenen Unterklasse |
| Höhe der Statusleiste | `qt_controls_pyrs/compact.py` | `StatusBarButton` — eine Statusleiste ist so hoch wie ihr höchstes Element |
| Einen Satz in der Hilfe, eine Formel, einen Quelltextverweis | `app/oberflaeche/hilfetexte/*.html` | eine Datei je Kapitel; `<<formel …>>` und `<<quelle …>>` sind die einzigen zwei Marken |
| Ein neues Hilfekapitel | `app/oberflaeche/hilfetexte/` | eine Datei `08-name.html` mit `titel:` in der ersten Zeile — mehr nicht |
| Farben, Schriftgröße, Stylesheet | `app/oberflaeche/darstellung.py` | `PALETTE`, `FONT_SIZE_OFFSET_PT`, `stylesheet()`, `HALO_OVERRIDES` |
| Wie ein Element **gezeichnet** wird (Halo, Animation, Pfeile) | `QtControlsPyRS` | die Klasse dort; `Compact…` erbt und ändert nur Zahlen |

Die Faustregel dahinter: **was ein Feld bedeutet**, steht in der Beschreibung;
**wie groß und wie dicht** die Oberfläche gesetzt ist, in
`qt_controls_pyrs/compact.py`; **wie sie aussieht**, in
`app/oberflaeche/darstellung.py` und in der Bibliothek; **was ein Tab tut**,
im Tab.

Ein Knopf dazwischen, der alles auf einmal verstellt: `FONT_SIZE_OFFSET_PT` in
`app/oberflaeche/darstellung.py`. Die Schrift bestimmt Zeilenhöhen,
Feldgrößen und Rahmen gleich mit — ein Punkt weniger macht die ganze
Oberfläche spürbar kompakter, ohne dass eine einzige Zahl von Hand nachgezogen
werden muss.

> **Die Bibliothek ist geteilt — und sie bestimmt nur das Aussehen.**
> `QtControlsPyRS` bedient mehrere Anwendungen, und sie sollen alle gleich
> aussehen: deshalb liegen die Bedienelemente und ihre Maße dort. Was
> festlegt, **was wo steht**, gehört hierher — der Formularbau, der
> Fensterzustand und die Entprellung lagen kurzzeitig dort und sind am
> 2026-10-31 zurückgekommen.
>
> Umgekehrt heißt das: eine Änderung an `COMPACT_HEIGHT` ändert jedes Fenster
> jeder dieser Anwendungen. Soll nur TRXing anders aussehen, gehört die
> Änderung nach `app/oberflaeche/darstellung.py` oder in eine eigene
> Unterklasse hier — so entstand `EinspaltigesRaster` in
> `app/vakuum/tab.py`.
>
> Die Vorbilder (`HaloButton`, `NumberField`, …) bleiben dabei unangetastet:
> `tests/test_compact.py` in der Bibliothek nagelt ihre Maße fest, damit
> niemand den bequemen Weg nimmt und `HaloButton.HEIGHT` von 45 auf 26 setzt —
> das würde Fenster verändern, die gerade niemand offen hat.

> **Eine Falle, die zweimal zugeschlagen hat.** `setMinimumWidth()` und jede
> Kastenangabe im Stylesheet (`margin`, `padding`, auch mit Wert `0`) sind
> **ausdrückliche Vorgaben** und schlagen das, was ein Widget selbst ausrechnet.
> So verdeckte in jedem Rahmen die Überschrift die erste Zeile, und so stand in
> einem Stückzahlfeld `:glich` statt `so viele wie moeglich`. Wer eine solche
> Vorgabe setzt, meint fast immer eine Untergrenze — dann gehört ein `max(…)`
> dazu.

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
`app/fach/legemuster.py` angemeldet ist. Verfügbar sind `auto`,
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
# 1. Bedienspalte beschreiben und den Tab bauen (app/<scheibe>/tab.py)
BEDIENSPALTE = [
    Gruppe("Eingaben", [
        [Zahl("breite", "Breite", "mm", dict(min=0.0, max=5000.0))],
    ]),
    Raster("results", "Ergebnis"),
]

class MeinTab(TabHost):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.ui = Oberflaeche()
        felder, self.ui = baue(BEDIENSPALTE, self.ui)
        ...  # context.state, context.settings, context.reporter, ...

# 2. Modulvertrag erfüllen
class MeinModul:
    module_id = "mein_modul"
    title = "Mein Modul"
    order = 40

    def create_widget(self, context: AppContext) -> QWidget:
        return MeinTab(context)

# 3. In app/tabs.py eintragen
def default_modules():
    return [PalletModule(), VacuumModule(), MeinModul()]
```

`tests/test_architecture.py` prüft, dass jedes registrierte Modul den Vertrag
erfüllt und dass das Hauptfenster kein Modul beim Namen nennt.
`tests/test_formularbau.py` prüft, dass jeder Name, den der Tab unter
`self.ui` anspricht, von seiner Beschreibung auch gebaut wird — und dass kein
Name zweimal vergeben ist.

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
Zeichnungen (`app/oberflaeche/darstellung.py`), dem Qt-Stil *Fusion* — der einzige,
der eine eigene Palette vollständig durchreicht — und dem Stylesheet in
`app/oberflaeche/darkstyle/` für Rollbalken, Ankreuzfelder und Aufklapppfeile samt
ihrer Bildchen. Verdrahtet ist das in `app/oberflaeche/darstellung.py`.

### Programmsymbol

`app/oberflaeche/icons/pallet.ico` — eine Datei für zwei Zwecke: die Anwendung setzt sie
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
| **Schriftgröße aller Bedienelemente** | `app/oberflaeche/darstellung.py` | `FONT_SIZE_OFFSET_PT` |
| **Fenstergröße beim ersten Start** | `app/start.py` | `DEFAULT_SIZE` |
| Aufteilung Palettierung | `app/palette/tab.py` | `SPLITTER_SIZES` |
| Aufteilung Vakuumplatte | `app/vakuum/tab.py` | `SPLITTER_SIZES` |

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
