"""Formulare als Daten beschreiben statt als XML zeichnen.

Bis Oktober 2026 lag die Anordnung der Bedienelemente in .ui-Dateien des Qt
Designer, aus denen tools/build_ui.py die ui_*.py erzeugte. Das kostete 1054
Zeilen XML und 687 Zeilen erzeugten Quelltext - und brachte nichts zurueck:
die eigenen Bedienelemente erscheinen im Designer als leere graue Kaesten,
weil er hochgestufte Widgets als ihre Basisklasse zeichnet. Ansehen liess sich
das Formular dort also gerade nicht.

Schlimmer als die Menge war die Teilung. Eine einzige Zeile des Formulars
stand an drei Stellen:

    tab.ui     <widget class="QLabel" name="plate_length_caption">
               <property name="text"><string>Plattenlaenge [mm]</string>
    ui_tab.py  (erzeugt, vier Zeilen)
    tab.py     configure("mm", minimum=10.0, maximum=3000.0, decimals=0)

Die Beschriftung in der XML, die Einheit im Quelltext, die Grenzen auch. Wer
die Einheit aenderte, musste zwei Dateien anfassen und hoffte, die dritte sei
erzeugt.

Hier steht dieselbe Zeile einmal:

    Zahl("plate_length", "Plattenlaenge", "mm", min=10, max=3000, schritt=10)

Die Bausteine sind eingefrorene Datenobjekte ohne Verhalten - sie BESCHREIBEN
eine Zeile, sie bauen sie nicht. Gebaut wird in baue(), und zwar genau einmal
je Baustein. Ein neuer Zeilentyp braucht deshalb eine Klasse und einen Zweig,
nicht mehr.

Was hier NICHT hingehoert: die Umgebung eines Tabs - Teiler, Rollflaechen, die
Zeichenflaeche, die 3D-Szene. Das sind Einzelstuecke und keine
Formularzeilen; sie stehen weiterhin im Quelltext des Tabs. Dieses Modul baut
Formulare, keine Fenster.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
)

from app.oberflaeche.bedienelemente import (
    IntField, KompaktButton, KompaktCheckBox, KompaktDropdown, KompaktGroupBox,
    KompaktLineEdit, KompaktRadioButton, NumberField, ResultGrid, compact_combo
)


# ==============================
# Die Bausteine
# ==============================

@dataclass(frozen=True, slots=True)
class Zahl:
    """Ein Zahlenfeld mit Einheit und Platz fuer eine Meldung.

    `optionen` geht unveraendert an NumberField.configure() - dort stehen
    Grenzen, Nachkommastellen und Schrittweite. Die Kurznamen min/max/schritt
    sind nur bequemer zu schreiben; uebersetzt wird in baue().
    """

    name: str
    beschriftung: str
    einheit: str = ""
    optionen: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Ganzzahl:
    """Ein Stueckzahlfeld mit Einheit."""

    name: str
    beschriftung: str
    einheit: str = ""
    optionen: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Wahl:
    """Ein Auswahlfeld. Gefuellt wird es spaeter vom Tab aus der Konfiguration."""

    name: str
    beschriftung: str
    #: Breitenbremse gegen lange Eintraege - siehe compact_combo().
    zeichen: int = 12
    hinweis: str = ""
    #: Mindestbreite in Bildpunkten. 0 heisst: was compact_combo vorgibt.
    mindestbreite: int = 0


@dataclass(frozen=True, slots=True)
class Text:
    """Ein einzeiliges Eingabefeld."""

    name: str
    beschriftung: str
    platzhalter: str = ""


@dataclass(frozen=True, slots=True)
class Schalter:
    """Ein Kaestchen zum Anhaken. Die Beschriftung steht daneben, nicht davor."""

    name: str
    beschriftung: str
    angehakt: bool = False
    hinweis: str = ""


@dataclass(frozen=True, slots=True)
class Auswahlknopf:
    """Ein Auswahlknopf. Mehrere nebeneinander schliessen einander aus."""

    name: str
    beschriftung: str
    angehakt: bool = False
    hinweis: str = ""


@dataclass(frozen=True, slots=True)
class Knopf:
    """Ein Knopf.

    `vorgabe` ist der Knopf, den die Eingabetaste ausloest; `aktiv` und
    `sichtbar` sind der Anfangszustand, den der Tab spaeter umschaltet - der
    Abbrechen-Knopf beginnt gesperrt, die Kameratuecke unsichtbar.
    """

    name: str
    beschriftung: str
    vorgabe: bool = False
    aktiv: bool = True
    sichtbar: bool = True
    hinweis: str = ""


@dataclass(frozen=True, slots=True)
class Hinweis:
    """Ein Erklaerungstext unter einer Zeile. Laeuft ueber die ganze Breite."""

    text: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class Raster:
    """Ein Ergebnisraster. Die Zeilen traegt der Tab nach, sie sind Ergebnis."""

    name: str
    titel: str = "Ergebnis"


@dataclass(frozen=True, slots=True)
class Platz:
    """Ein leerer Platzhalter, den der Tab selbst fuellt.

    Fuer die Zeichenflaeche, die 3D-Szene und das Paketformular: sie brauchen
    den AppContext oder ein Ergebnis und lassen sich deshalb nicht aus einer
    Beschreibung bauen. Hier wird nur der Platz freigehalten.
    """

    name: str


@dataclass(frozen=True, slots=True)
class Zeile:
    """Mehrere Bedienelemente nebeneinander, ohne Gruppenrahmen.

    Fuer Knopfreihen und Leisten. Mit `dehnen` faellt rechts der uebrige Platz
    an - sonst schwimmen zwei Knoepfe in voller Breite auseinander.
    """

    zellen: list[Any]
    dehnen: bool = False


@dataclass(frozen=True, slots=True)
class Gruppe:
    """Ein Gruppenrahmen mit Ueberschrift und Zeilen darin.

    `zeilen` ist eine Liste von Listen: jede innere Liste ist eine Zeile des
    Rasters, jeder Eintrag darin eine Zelle. So steht im Quelltext dasselbe
    Bild wie auf dem Schirm - vier Felder nebeneinander sind vier Eintraege
    in einer Zeile.
    """

    titel: str
    zeilen: list[list[Any]]
    name: str = ""

    #: Beschriftung ueber dem Feld statt daneben.
    #:
    #: Nebeneinander addieren sich Beschriftung und Feld; stehen zwei Paare in
    #: einer Zeile, addieren sich vier Breiten. Gemessen am Vakuumtab:
    #: "Saugerabstand" 156 + Feld 104 + "Beschleunigung" 168 + Feld 104 - die
    #: Spalte brauchte 650 Bildpunkte, obwohl die Felder selbst nur 104 messen.
    #:
    #: Uebereinander zaehlt je Spalte das GROESSERE von beiden statt ihrer
    #: Summe. Das kostet eine Zeilenhoehe je Zeile und spart ein Drittel
    #: Breite - und die Breite ist das knappe Gut, weil daneben die Zeichnung
    #: steht.
    oben: bool = False


# ==============================
# Der Erbauer
# ==============================

class Oberflaeche:
    """Die gebauten Bedienelemente, ansprechbar ueber ihren Namen.

    Ersetzt die erzeugte Ui_-Klasse. Der Zugriff bleibt derselbe -
    `self.ui.plate_length` - damit die Tabs unveraendert weiterarbeiten.
    """

    def __getattr__(self, name: str):
        # Nur erreichbar, wenn das Attribut NICHT gesetzt wurde: dann ist ein
        # Name gemeint, den die Beschreibung nicht kennt.
        raise AttributeError(
            "Die Oberflaeche kennt kein Element '" + name + "'. "
            "Bekannt sind: " + ", ".join(sorted(vars(self)))
        )

    def namen(self) -> tuple[str, ...]:
        return tuple(sorted(vars(self)))


#: Kurznamen der Zahlenfelder -> die Namen, die configure() erwartet.
_OPTIONEN = {
    "min": "minimum", "max": "maximum", "schritt": "step",
    "stellen": "decimals", "wert": "value", "hinweis": "tooltip",
    "null_text": "special_zero_text",
}


def _configure_optionen(optionen: dict[str, Any]) -> dict[str, Any]:
    return {_OPTIONEN.get(schluessel, schluessel): wert for schluessel, wert in optionen.items()}


def _beschriftung(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


#: Mindestbreite eines Hinweistextes.
#:
#: Ohne sie bricht ein langer Hinweis in eine Saeule von zwei Woertern um und
#: zieht die Zeile in die Hoehe - die Rollflaeche gibt ihre Breite nicht nach
#: aussen weiter, also nimmt der Text, was er bekommt. Derselbe Wert stand
#: frueher als minimumSize in der .ui-Datei.
HINWEIS_BREITE = 240


def _hinweis(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(HINWEIS_BREITE)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    # Die Rolle greift das Stylesheet ab - so bleiben Hinweise ueberall gleich
    # blass, ohne dass hier eine Farbe steht.
    label.setProperty("role", "note")
    return label


def _zelle(baustein: Any, ziel: Oberflaeche) -> tuple[QWidget | None, QWidget]:
    """(Beschriftung, Bedienelement) eines Bausteins. Beschriftung darf fehlen."""
    if isinstance(baustein, Zahl):
        feld = NumberField(baustein.einheit)
        feld.configure(baustein.einheit, **_configure_optionen(baustein.optionen))
        setattr(ziel, baustein.name, feld)
        return _beschriftung(baustein.beschriftung), feld

    if isinstance(baustein, Ganzzahl):
        feld = IntField(baustein.einheit)
        feld.configure(baustein.einheit, **_configure_optionen(baustein.optionen))
        setattr(ziel, baustein.name, feld)
        return _beschriftung(baustein.beschriftung), feld

    if isinstance(baustein, Wahl):
        box = KompaktDropdown()
        compact_combo(box, min_chars=baustein.zeichen, tooltip=baustein.hinweis)
        if baustein.mindestbreite:
            box.setMinimumWidth(baustein.mindestbreite)
        setattr(ziel, baustein.name, box)
        return _beschriftung(baustein.beschriftung), box

    if isinstance(baustein, Text):
        feld = KompaktLineEdit()
        if baustein.platzhalter:
            feld.setPlaceholderText(baustein.platzhalter)
        setattr(ziel, baustein.name, feld)
        return _beschriftung(baustein.beschriftung), feld

    if isinstance(baustein, Schalter):
        box = KompaktCheckBox(baustein.beschriftung)
        box.setChecked(baustein.angehakt)
        if baustein.hinweis:
            box.setToolTip(baustein.hinweis)
        setattr(ziel, baustein.name, box)
        return None, box

    if isinstance(baustein, Auswahlknopf):
        knopf = KompaktRadioButton(baustein.beschriftung)
        knopf.setChecked(baustein.angehakt)
        if baustein.hinweis:
            knopf.setToolTip(baustein.hinweis)
        setattr(ziel, baustein.name, knopf)
        return None, knopf

    if isinstance(baustein, Knopf):
        knopf = KompaktButton(baustein.beschriftung)
        knopf.setDefault(baustein.vorgabe)
        knopf.setEnabled(baustein.aktiv)
        knopf.setVisible(baustein.sichtbar)
        if baustein.hinweis:
            knopf.setToolTip(baustein.hinweis)
        setattr(ziel, baustein.name, knopf)
        return None, knopf

    if isinstance(baustein, Hinweis):
        label = _hinweis(baustein.text)
        if baustein.name:
            setattr(ziel, baustein.name, label)
        return None, label

    if isinstance(baustein, Raster):
        raster = ResultGrid(baustein.titel)
        setattr(ziel, baustein.name, raster)
        return None, raster

    if isinstance(baustein, Platz):
        platz = QWidget()
        setattr(ziel, baustein.name, platz)
        return None, platz

    raise TypeError("Unbekannter Baustein: " + type(baustein).__name__)


def _spannt_volle_breite(baustein: Any) -> bool:
    """Ob die Zelle allein in ihrer Zeile steht und sie ganz ausfuellt."""
    return isinstance(baustein, (Hinweis, Raster, Platz))


def baue_gruppe(gruppe: Gruppe, ziel: Oberflaeche) -> KompaktGroupBox:
    """Baut einen Gruppenrahmen aus seiner Beschreibung."""
    box = KompaktGroupBox(gruppe.titel)
    if gruppe.name:
        setattr(ziel, gruppe.name, box)

    raster = QGridLayout(box)
    raster.setHorizontalSpacing(8)
    raster.setVerticalSpacing(4)

    breiteste = max((len(zeile) for zeile in gruppe.zeilen), default=1)

    if gruppe.oben:
        # Je Baustein eine Rasterspalte; die Beschriftung sitzt in einer
        # eigenen Zeile darueber. Zwei Rasterzeilen je Formularzeile.
        for nummer, zeile in enumerate(gruppe.zeilen):
            kopf, feld = nummer * 2, nummer * 2 + 1
            for spalte, baustein in enumerate(zeile):
                label, widget = _zelle(baustein, ziel)
                if _spannt_volle_breite(baustein) or label is None:
                    # Hinweise, Kaestchen und Raster brauchen keinen Kopf -
                    # sie bringen ihre Beschriftung selbst mit oder sind eine.
                    raster.addWidget(widget, kopf, 0, 2, breiteste)
                    break
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
                raster.addWidget(label, kopf, spalte)
                raster.addWidget(widget, feld, spalte)
        for spalte in range(breiteste):
            raster.setColumnStretch(spalte, 1)
        return box

    for nummer, zeile in enumerate(gruppe.zeilen):
        spalte = 0
        for baustein in zeile:
            label, widget = _zelle(baustein, ziel)
            if _spannt_volle_breite(baustein):
                raster.addWidget(widget, nummer, 0, 1, breiteste * 2)
                spalte = breiteste * 2
                continue
            if label is not None:
                raster.addWidget(label, nummer, spalte)
                spalte += 1
            # Eine Zelle ohne Beschriftung nimmt deren Platz mit ein, sonst
            # rutschten die folgenden Spalten gegeneinander.
            spannweite = 1 if label is not None else 2
            raster.addWidget(widget, nummer, spalte, 1, spannweite)
            spalte += spannweite

    # JEDE Feldspalte traegt Dehnraum, nicht nur die letzte.
    #
    # Mit Dehnraum allein hinten blieben alle uebrigen Feldspalten auf ihrer
    # Mindestbreite stehen, und der ganze Ueberschuss fiel rechts an. Sichtbar
    # wurde das an der Warnmeldung unter "Max. Stapellast": sie sass in Spalte
    # 1 von acht, bekam gut hundert Bildpunkte und brach sechszeilig um -
    # mitten in einem Formular, das tausend Bildpunkte breit war.
    #
    # Die Beschriftungsspalten bleiben ohne: sie sollen so breit sein wie ihr
    # Text und nicht mitwachsen.
    for spalte in range(1, breiteste * 2, 2):
        raster.setColumnStretch(spalte, 1)
    return box


def baue(gruppen: list[Gruppe], ziel: Oberflaeche | None = None) -> tuple[QWidget, Oberflaeche]:
    """Baut ein ganzes Formular. Gibt (Widget, Oberflaeche) zurueck.

    Das Widget haengt der Tab dort ein, wo es hingehoert; die Oberflaeche ist
    das Gegenstueck zur frueheren Ui_-Klasse.
    """
    ziel = ziel if ziel is not None else Oberflaeche()
    behaelter = QWidget()
    aussen = QVBoxLayout(behaelter)
    aussen.setContentsMargins(0, 0, 0, 0)
    aussen.setSpacing(6)

    for eintrag in gruppen:
        if isinstance(eintrag, Gruppe):
            aussen.addWidget(baue_gruppe(eintrag, ziel))
        elif isinstance(eintrag, Zeile):
            reihe = QHBoxLayout()
            reihe.setContentsMargins(0, 0, 0, 0)
            reihe.setSpacing(6)
            for baustein in eintrag.zellen:
                label, widget = _zelle(baustein, ziel)
                if label is not None:
                    reihe.addWidget(label)
                reihe.addWidget(widget)
            if eintrag.dehnen:
                reihe.addStretch(1)
            aussen.addLayout(reihe)
        else:
            # Ein einzelnes Element ohne Rahmen - etwa ein Ergebnisraster.
            _label, widget = _zelle(eintrag, ziel)
            aussen.addWidget(widget)

    aussen.addStretch(1)
    return behaelter, ziel
