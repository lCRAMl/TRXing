# Architektur

## Schichten und Datenflussrichtung

```
                        ┌───────────────────────────┐
                        │           GUI             │
                        │   Fenster / Tabs / Widgets│
                        └────────────┬──────────────┘
                                     │ DTOs
                        ┌────────────▼──────────────┐   ┌──────────────────┐
                        │         SERVICES          │──▶│  VISUALIZATION   │
                        │   öffentliche GUI-API     │   │  2D / 3D-Adapter │
                        └──────┬─────────────┬──────┘   └──────────────────┘
                               │             │
                   ┌───────────▼───┐   ┌─────▼──────────┐
                   │     JOBS      │   │     CONFIG     │
                   │ Worker / Pools│   │ Loader / Schema│
                   └───────────┬───┘   └─────┬──────────┘
                               │             │
                        ┌──────▼─────────────▼──────┐
                        │          ENGINES          │
                        │  Palettierung / Vakuum    │
                        └────────────┬──────────────┘
                                     │
                        ┌────────────▼──────────────┐
                        │           DTO             │
                        └────────────┬──────────────┘
                                     │
                        ┌────────────▼──────────────┐
                        │           CORE            │
                        │ errors / units / jobs-frei│
                        └───────────────────────────┘
```

Jede Schicht greift nur nach unten. Die Regeln stehen maschinenlesbar in
`tests/test_architecture.py` und werden bei jedem Testlauf geprüft.

| Schicht | darf importieren | darf **nicht** importieren |
|---|---|---|
| `core` | nur Standardbibliothek | alles aus `app`, Qt |
| `dto` | `core` | Qt, alles darüber |
| `engines` | `core`, `dto` | Qt, `config`, `services`, `jobs`, `gui` |
| `config` | `core`, `dto` | Qt, `engines`, `services`, `gui` |
| `jobs` | `core`, Qt | `engines`, `services`, `gui` |
| `services` | `core`, `dto`, `config`, `engines`, `jobs`, `QtCore` | `QtWidgets`, `QtGui`, `visualization`, `gui` |
| `visualization` | `core`, `dto`, Qt | `engines`, `services`, `jobs`, `config`, `gui` |
| `gui` | `core`, `dto`, `services`, `jobs`, `visualization` | `engines`, `config.loader`, `config.schema`, `json` |

### Bewusste Abweichungen vom Entwurf in doc/01.txt

**`CalculationModule` liegt in `app/gui/module_registry.py`, nicht in
`services/module_service.py`.** Der Vertrag liefert ein `QWidget` und ist damit
ein Belang der Oberfläche. Dadurch bleibt die Serviceschicht frei von
`QtWidgets` — eine schärfere Trennung, als der Entwurf verlangt, und
maschinell prüfbar.

**Die Farbpalette liegt in `app/visualization/theme.py`.** 2D- und 3D-Renderer
brauchen dieselben Farben wie die Bedienelemente. Läge sie in `app/gui`, müsste
`app/visualization` dorthin zurückgreifen — entgegen der Datenflussrichtung.
`app/gui/theme.py` holt sie von dort und ergänzt nur das Stylesheet.

**Services dürfen `QtCore`.** Signale sind der einzige threadsichere Weg, ein
Ergebnis aus einem Worker in die Oberfläche zu bringen. Verboten bleiben
Bedienelemente.

### Hell und dunkel: eine Entscheidung, beim Import

Es gibt zwei Paletten, `LIGHT` und `DARK`. Welche gilt, steht in `PALETTE` und
wird **einmal beim Import** entschieden — abgefragt wird die Einstellung von
Windows in `app/core/os_theme.py` (Registry, Qt-frei, übersteuerbar mit
`TRXING_THEME`).

Der Zeitpunkt ist der Punkt, auf den es ankommt. Ein Dutzend Module holt sich
beim Import `from … import PALETTE` und hält die Palette danach als Objekt
fest. Ein Austausch zur Laufzeit erreichte diese Module nicht: sie zeigten
weiter die alten Farben, und die Anzeige wäre halb hell und halb dunkel. Ein
Wechsel des Windows-Modus wirkt deshalb beim nächsten Start.

Die Abfrage gehört aus zwei Gründen in `app/core` und nicht in die Oberfläche:
`app/visualization/theme.py` braucht die Antwort, darf Qt aber nicht kennen —
und die Antwort muss vor der `QApplication` feststehen, womit
`QStyleHints.colorScheme()` ausscheidet.

Was Qt daraus macht, steht in `app/gui/theme.py`: der Stil *Fusion* (der
einzige, der eine eigene Palette vollständig durchreicht), die `QPalette` mit
denselben Farbwerten und das Stylesheet aus `app/gui/darkstyle/` für die
Feinheiten, für die eine Palette nicht reicht. `apply_theme()` setzt beides vor
dem ersten Fenster; danach erreicht eine Palette bereits erzeugte Widgets nur
noch teilweise.

Für die Zeichnungen gilt dieselbe Trennung: `app/visualization/colors.py`
kennt die Richtung, nicht die Farbe. Eine blasse Füllung wird auf hellem Grund
aufgehellt und auf dunklem abgedunkelt — beides rückt sie an den Hintergrund
heran und lässt den Ring die Aussage tragen.

---

## Die Oberfläche ist noch einmal geteilt

Innerhalb von `app/gui` verläuft eine zweite Grenze — zwischen **Anordnung**
und **Verhalten**:

```
vacuum_tab.ui          Anordnung, Gruppen, Beschriftungen, Größenrichtlinien
   │                   im Qt Designer bearbeitet
   │ pyuic6  (tools/build_ui.py)
   ▼
Ui_VacuumTab           erzeugt, nicht von Hand geändert
   │
   ▼
VacuumTab              ├── Events        Signale der Bedienelemente
                       ├── Berechnung    Eingaben → DTO → Service
                       ├── State         AppState lesen und schreiben
                       ├── Service       calculate_async, Ergebnis-Signale
                       └── Ergebnisanzeige
```

**Nicht jede Layoutdatei ist ein Tab.** Die Paketdaten sind die gemeinsame
Eingabe beider Module und kein Berechnungsprogramm; ihr Formular
(`app/gui/package/package_form.ui` und `.py`) sitzt am Kopf der Palettierung und
unterliegt derselben Trennung. Der Tab hängt es ein und reicht ihm die drei
Lebenszeichen weiter, die er selbst von außen bekommt — Zustandsänderung,
Übernahme, Ende. Eingehängt wird im Quelltext und nicht als hochgestufte Klasse
im Designer, weil das Formular den `AppContext` braucht; die Layoutdatei hält
nur den Platz frei (`package_host`), so wie sie es für die 3D-Szene tut.

Dass die Bedienspalte der Palettierung seither in einer Rollfläche steckt, ist
die Folge davon: Formular und Spalte zusammen sind höher als ein Fenster von
860 Bildpunkten. Ohne sie wäre die Mindesthöhe des Fensters auf über 1000
Bildpunkte gestiegen, und auf einem 768er Bildschirm ließe sich die Anwendung
nicht mehr benutzen.

**Zusammensetzung, nicht Mehrfachvererbung.** Der Tab hält seine erzeugte
Klasse als `self.ui`, statt von ihr zu erben. Beide Wege sind üblich; die
Zusammensetzung gewinnt hier, weil die erzeugten Namen dann bündig
beieinanderliegen: sie können weder mit denen von `QWidget` noch mit eigenen
kollidieren, und beim Lesen ist sofort erkennbar, was aus dem Designer stammt.
`tests/test_ui_files.py` prüft beides.

**Kompiliert, nicht zur Laufzeit geladen.** Die erzeugte Datei nennt jedes
Widget als Attribut: der Editor vervollständigt sie, ein Tippfehler im
Objektnamen fällt beim Schreiben auf statt beim Öffnen des Tabs, und das Paket
braucht die XML-Dateien nicht mitzunehmen. Der Preis ist der Zwischenschritt —
`AUTOBUILD.py` führt ihn vor dem Paketieren aus, und `tests/test_ui_files.py`
übersetzt bei jedem Testlauf neu und vergleicht mit der eingecheckten Datei.
Ein Vergleich über Zeitmarken wäre wertlos: nach einem frischen Auschecken
tragen alle Dateien dieselbe Zeit.

**Was in der Layoutdatei nichts verloren hat.** Wertebereiche, Einheiten und
Schrittweiten stehen im Quelltext (`_configure_fields`), die Zeilen der
Ergebnisanzeige ebenfalls (`_build_result_rows`). Dass eine Länge in
Millimetern angegeben wird und höchstens 5000 betragen darf, ist Fachwissen und
keine Gestaltung — in der XML-Datei läge es als namenlose Eigenschaft ohne jede
Prüfung. Farben ebenso: die Layoutdatei setzt `role="note"`, das Aussehen steht
einmal im Stylesheet in `app/gui/theme.py`.

**Was der Designer nicht speichern kann,** steht in `_configure_layout()`: die
Aufteilung eines Splitters, die Streckung des Wurzellayouts und die
`QButtonGroup` mit stabilen Nummern für die Ansichtswahl.

**Zwei Fallstricke, die maschinell abgefangen werden,** weil sie erst im
fertigen Fenster auffallen:

* Die Eigenschaft **`stretch`** an einem Layout. Der Designer bietet sie an,
  pyuic6 erzeugt daraus `setStretch("0,1")`, und das scheitert zur Laufzeit —
  beim Öffnen des Tabs, weit weg von der Ursache. `tools/build_ui.py` weist die
  Datei mit einer Erklärung zurück; dasselbe Ergebnis erreicht man mit
  Größenrichtlinien.
* Ein umbrechender Hinweistext **ohne Mindestbreite**. Qt schätzt seine Höhe
  für genau die gesetzte Breite; bei 1 bricht der Text rechnerisch nach jedem
  Wort um und meldet mehrere hundert Bildpunkte Höhe. Das Formular reserviert
  sie brav, und zwischen den Eingabefeldern klafft eine handbreite Lücke,
  während der Text darin in drei Zeilen steht.

---

## Einheitenkonvention

Definiert in `app/core/units.py`, erzwungen durch
`test_numeric_dto_fields_carry_a_unit_suffix`.

| Größe | Einheit | Feldsuffix |
|---|---|---|
| Länge | mm | `_mm` |
| Fläche | mm² | `_mm2` |
| Masse | kg | `_kg` |
| Kraft | N | `_n` |
| Druck | Pa | `_pa` |
| Volumenstrom | m³/s | `_m3s` |
| Beschleunigung | m/s² | `_ms2` |
| Anteil / Prozent | 0…1 / 0…100 | `_ratio` / `_pct` |

**Unterdruck ist immer eine positive Druckdifferenz.** Die im Datenblatt
übliche Schreibweise „−0,6 bar“ sind hier 60000 Pa. Ein negatives Vorzeichen im
Rechenweg wäre eine dauerhafte Fehlerquelle; umgerechnet wird erst in der
Anzeige.

---

## Schutz vor veralteten Ergebnissen

Zwei Mechanismen, die zusammengehören:

```
CancellationToken   bricht ab, was noch läuft      (app/core/cancellation.py)
RequestGate         verwirft, was überholt wurde   (app/core/requests.py)
```

Der Abbruch allein genügt nicht: zwischen „abgebrochen“ und „Ergebnis liegt
bereits im Signalpuffer“ gibt es ein Zeitfenster, das sich nicht schließen
lässt. `CalculationService._on_result` schließt es durch die Torprüfung.

Zusätzlich trägt jedes Ergebnis die `state_revision`, unter der es entstand.
Weicht sie von `AppState.revision` ab, ist die Anzeige überholt — daran erkennen
jeder Tab eine Änderung der Paketdaten, ohne dass Signale von Tab zu Tab
gereicht werden.

Ein überholtes Ergebnis wird **nachgerechnet, nicht gemeldet**. Ist der Tab
sichtbar, sofort (entprellt); ist er verdeckt, wird die Änderung in
`_needs_recalculation` vorgemerkt und in `on_activated()` beim Aufschlagen
nachgeholt. So brennt kein Rechenlauf für ein Ergebnis, das niemand ansieht,
und wer den Tab öffnet, sieht nie eine veraltete Zahl.

---

## Herkunft der physikalischen Kennwerte

`app/dto/suction.py` und `config/suction_cups.json` führen für jeden Wert seine
Quelle. Drei Klassen, in der Oberfläche unterschieden:

| Klasse | Bedeutung | Beispiel |
|---|---|---|
| `datasheet` | aus dem Herstellerdatenblatt | Saugkraft 14,4 N bei −0,6 bar |
| `config` | Benutzer- oder Anlagenangabe | Kartonpermeabilität, Sicherheitsfaktor |
| `model` | Annahme des Rechenmodells | Ausflussbeiwert 0,8 |

### Die wirksame Saugfläche ist abgeleitet, nicht erfunden

Der Abgleich der Datenblattkräfte gegen die Geometrie zeigt, dass die
angegebene Kraft exakt `Δp × Kreisfläche(d2)` ist, mit d2 dem inneren
Faltendurchmesser:

| Typ | d2 | aus d2 berechnet | Datenblatt | Abweichung |
|---|---|---|---|---|
| SPB2 20 | 12,0 mm | 6,79 N | 6,8 N | −0,2 % |
| SPB2 25 | 14,5 mm | 9,91 N | 9,9 N | +0,1 % |
| SPB2 30 | 16,9 mm | 13,46 N | 14,4 N | **−6,5 %** |
| SPB2 40 | 22,9 mm | 24,71 N | 24,8 N | −0,4 % |
| SPB2 50 | 27,1 mm | 34,61 N | 34,6 N | ±0 % |

Gerechnet wird mit der aus der **Datenblattkraft** zurückgerechneten Fläche
(`A = F / Δp_ref`): beim Bezugsdruck kommt exakt der Herstellerwert heraus, bei
anderem Unterdruck skaliert sie physikalisch richtig, und die Abweichung bei
SPB2 30 wird ausgewiesen statt stillschweigend korrigiert.

Der Bezugsdruck steht am Saugertyp (`reference_vacuum_pa`), nicht als Konstante
im Code — andere Hersteller beziehen auf −0,7 oder −0,8 bar.

---

## Der Arbeitspunkt

Die naheliegende Rechnung wäre: Sollvakuum annehmen, Kraft daraus bestimmen,
benötigten Volumenstrom danebenstellen, bei Überschreitung warnen. Sie liefert
ein Ergebnis, das als sicher ausgewiesen wird, obwohl es nie eintritt — schafft
der Erzeuger den Strom nicht, stellt sich das Sollvakuum eben nicht ein.

Gerechnet wird deshalb der Schnittpunkt zweier Kurven:

```
Bedarf    steigt mit dem Unterdruck   (mehr Druckdifferenz → mehr Fremdluft)
Angebot   fällt  mit dem Unterdruck   (Kennlinie des Erzeugers)
```

Gesucht per Bisektion; `Angebot − Bedarf` ist bei null Unterdruck positiv und
beim Sollwert negativ. Ein offener Sauger senkt damit unmittelbar die Traglast.

**Größenordnung:** ein ungedrosselter offener SPB2 30 zieht bei −0,6 bar rund
7 m³/h, ein SPB2 50 rund 17 m³/h. Das übersteigt die Leistung vieler
Vakuumerzeuger — Strombegrenzer und Rückschlagventile sind der Regelfall, nicht
die Ausnahme. Voreingestellt ist deshalb `check_valve`.

---

## Gemeinsame Musterschicht

Spezifikation 18 verlangt, dass die Vakuumplatte ein in der Palettierung gewähltes Muster
wiederverwenden kann, ohne die Palettierlogik zu duplizieren. Der Schlüssel:
**ein Muster kennt keine Palette.** Es füllt ein Rechteck mit gleichen
Rechtecken.

```
PatternRequest (Rechteck + Elementmaß)
        │
        ├──▶ Palettierung: Palettenfläche
        └──▶ Vakuumplatte: Plattenfläche
```

Ein neues Muster braucht eine Funktion mit dieser Signatur und einen Eintrag in
`config/pallet_patterns.json` — keinen Eingriff in Optimierer oder Oberfläche.

### Lückenfreiheit ist eine harte Zusage

Eine Lücke mitten in der Ladung ist kein Schönheitsfehler: die Pakete
verrutschen darin beim Transport. `test_no_pattern_leaves_gaps_between_packages`
prüft deshalb jedes Muster gegen sechs Paketformate auf **eingeschlossene**
Hohlräume (Rasterabtastung mit Flutfüllen vom Rand her). Ein freier Streifen am
Außenrand bleibt erlaubt — er lässt sich bei keiner Paketgröße vermeiden.

Möglich wird das durch `alternating_bands()`: mischt ein Muster zwei
Ausrichtungen, entsteht es aus waagerechten Bändern voller Reihen statt aus
einem Feldraster. Bei quadratischen Paketen bleibt der feldweise Wechsel, weil
er dort exakt aufgeht.

| Muster | Band k gedreht, wenn |
|---|---|
| Schachbrett | k ungerade |
| Windrad | (k div 2) ungerade |
| Spiralverband | min(k, n−1−k) ungerade |
| Randverband | k weder erstes noch letztes Band |

---

## Saugermuster

`app/engines/vacuum/arrangements.py` führt eine Registry wie die
Palettiermuster: ein neues Muster braucht eine Funktion und einen
Registryeintrag, keinen Eingriff in Verteillogik, Service oder Tab. Die
Oberfläche füllt ihr Auswahlfeld aus `VacuumService.available_arrangements()`.

Die harte Zusage jedes Musters, geprüft über fünf Plattengrößen:

* kein Sauger ragt über die nutzbare Fläche hinaus,
* keine zwei Sauger unterschreiten den Mindestabstand.

Beim Dreiecksgitter hängt Letzteres an einem Detail: der **gesamte Block** wird
einmal zentriert, nicht jede Reihe für sich. Reihenweises Zentrieren zerstört
den Versatz von einem halben Rastermaß — gemessen 39,7 statt 44 mm, die Sauger
würden sich überlappen.

### Eine gewünschte Stückzahl treffen

Überzählige Sauger wegzulassen ergäbe eine Platte, die unten dicht bestückt ist
und oben leer bleibt. Stattdessen wird das Rastermaß vergrößert, bis das Muster
von selbst etwa die gewünschte Zahl liefert (Intervallhalbierung, die Anzahl
fällt monoton); der kleine Rest wird von der obersten Reihe her abgeräumt. Das
funktioniert für jedes Muster und erhält seine Form.

### Reihenfolge im Rechner

Seit es das Muster *nur über den Paketen* gibt, läuft die Paketanordnung
**vor** der Saugerverteilung — sie braucht die Kartonflächen, um zu
entscheiden, wo ein Sauger überhaupt sinnvoll ist. Umgekehrt braucht die
Paketanordnung nichts von den Saugern.

---

## Leistungsentscheidungen

| Stelle | Problem | Lösung | Messung |
|---|---|---|---|
| `loads.analyze` | Kaskade verglich jedes Paket mit jedem darunter | Rasterindex über die Standflächen | 75 s → **0,9 s** bei 148 800 Paketen |
| `loads.analyze` | rechnete auch ohne Grenzwert | frühe Rückgabe, wenn keine Stapellast gesetzt | entfällt vollständig |
| `pallet_3d._boxes_to_mesh` | `pv.Cube` je Paket, dann `merge` | Eckpunkte und Flächen in zwei numpy-Operationen | 36 s → **0,10 s** bei 52 800 Paketen |
| `pallet_3d` | Grafiklast beim Drehen der Kamera | oberhalb 4000 Körpern nur die sichtbare Hülle | 52 800 → 8 340 Körper |
| `solver.py` | CP-SAT war nicht reproduzierbar | ein Suchfaden, deterministisches Zeitbudget | Spezifikation 39 erfüllt |

### Obergrenzen

`MAX_PLACEMENTS_PER_LAYER = 10 000` und `MAX_TOTAL_PLACEMENTS = 200 000` sind
reine Riegel gegen Einheitenverwechslungen (ein Paket von 1 × 1 mm ergäbe
960 000 Stück je Lage), keine Leistungsgrenzen. Sie greifen vor dem Rechnen,
nicht danach.
