"""Die Hilfe: das Fenster und der Lader fuer ihre Kapitel.

Der Text selbst liegt in hilfetexte/ daneben, eine Datei je Kapitel. Bis
Oktober 2026 standen die sieben Kapitel als Zeichenkettenkonstanten hier:
890 der 1160 Zeilen waren HTML, und eine Datei, die zu drei Vierteln Text ist,
liest sich nicht mehr als Modul.

Der Grund, der frueher FUER den Quelltext sprach, gilt unveraendert und haengt
gar nicht daran: der Text verweist an jeder Stelle auf das Modul, das die
beschriebene Formel wirklich rechnet, und tests/test_help.py prueft, dass es
diese Module gibt. Eine Dokumentation, die beim Umbenennen stillschweigend ins
Leere zeigt, ist schlimmer als keine. Der Test liest das fertige Dokument und
nicht den Quelltext - ihm ist es gleich, woher die Kapitel kommen.

Zusammengelegt aus gui/help/content.py und gui/help/formula_dialog.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from app.oberflaeche.darstellung import PALETTE
from qt_controls_pyrs import HaloButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# content.py
# ---------------------------------------------------------------------------
"""Der Inhalt der Rechenwegdokumentation.

Getrennt vom Dialog, weil es Text ist und kein Bedienelement: so laesst er sich
ohne Qt pruefen, und ein spaeterer Export nach HTML oder PDF braucht den Dialog
nicht. Seit die Kapitel in hilfetexte/ liegen, ist die Trennung noch eine
Stufe weiter - wer einen Satz aendert, fasst kein Python an.

Anspruch: wer diese Seiten liest, kann jedes angezeigte Ergebnis von Hand
nachrechnen und findet im Quelltext die Stelle, an der es entsteht. Deshalb
steht bei jedem Abschnitt die Datei dabei, in der die Formel tatsaechlich
implementiert ist - eine Dokumentation, die man nicht gegen den Code halten
kann, veraltet unbemerkt.

Die Formeln stehen als Text, nicht als Bild: sie bleiben damit durchsuchbar,
kopierbar und in jeder Schriftgroesse lesbar.
"""

@dataclass(frozen=True, slots=True)
class Section:
    """Ein Kapitel der Dokumentation."""

    anchor: str
    title: str
    html: str


def _formula(*lines: str) -> str:
    """Formelblock in fester Laufweite.

    Der Inhalt wird maskiert. Ohne das zerlegt ein Vergleich wie "pi <= pi_krit"
    das ganze Dokument: das Anzeigefenster liest das Kleinerzeichen als Beginn
    eines HTML-Elements und verschluckt alles bis zum naechsten groesser-als -
    samt Formel und der Formatierung dahinter.

    Geschrieben wird durchgaengig in linearer Schreibweise (sqrt(...), ^, /)
    statt als gezeichneter Bruch. Zweistoeckige Ausdruecke aus Bindestrichen
    und Schraegstrichen verrutschen bei jeder anderen Schriftgroesse und lassen
    sich weder kopieren noch durchsuchen.
    """
    body = "\n".join(lines)
    body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Die Tabellenzelle ist ein Umweg, aber ein noetiger: Qt setzt jede Zeile
    # eines pre-Elements als eigenen Absatz mit eigenem Hintergrund, und der
    # Block zerfaellt in gestreifte Balken mit Luecken dazwischen. Eine Zelle
    # wird als eine Flaeche gezeichnet - und traegt als einziges Element auch
    # den farbigen Balken am linken Rand.
    return (
        '<table class="formula" width="100%" cellspacing="0" cellpadding="0">'
        "<tr><td><pre>" + body + "</pre></td></tr></table>"
    )


def _source(path: str, detail: str = "") -> str:
    """Verweis auf die Stelle im Quelltext, an der die Formel steht."""
    return ('<p class="source"><b>Im Quelltext:</b> <code>' + path + '</code>'
            + (" &ndash; " + detail if detail else "") + "</p>")


#: Das Stylesheet des Hilfefensters, aus der Farbpalette gebaut.
#:
#: Die Farben standen hier frueher fest verdrahtet - und waren genau die der
#: hellen Palette. In der dunklen Fassung faerbt Qt den Text der Anzeige weiss,
#: die Untergruende blieben aber hell: weisse Schrift auf weisser Tabelle. Aus
#: der Palette gebaut stimmen beide Fassungen, ohne dass die Texte etwas davon
#: wissen.
#:
#: Der Untergrund der Seite kommt NICHT von hier, sondern aus der Palette des
#: Widgets. Eine eigene Farbe hier wuerde sich vom Rand des Fensters abheben,
#: sobald jemand das Farbschema wechselt.
STYLE = """
body { font-family: 'Segoe UI', sans-serif; font-size: 10pt; line-height: 1.5;
       color: """ + PALETTE.text + """; }
h1 { font-size: 15pt; margin-top: 4px; margin-bottom: 2px; }
h2 { font-size: 12pt; margin-top: 20px; margin-bottom: 4px;
     border-bottom: 1px solid """ + PALETTE.border + """; padding-bottom: 3px; }
h3 { font-size: 10.5pt; margin-top: 14px; margin-bottom: 2px; }
p { margin: 5px 0; }
table.formula { margin: 9px 0; }
table.formula td { background: """ + PALETTE.surface_alt + """; border: none;
                   border-left: 3px solid """ + PALETTE.accent + """;
                   padding: 7px 12px; }
table.formula pre { font-family: Consolas, monospace; font-size: 10pt; margin: 0; }
p.source { font-size: 8.5pt; color: """ + PALETTE.text_muted + """; margin: 4px 0 10px 0; }
code { font-family: Consolas, monospace; font-size: 9pt; }
table { border-collapse: collapse; margin: 8px 0; }
td, th { border: 1px solid """ + PALETTE.border + """; padding: 3px 9px; font-size: 9.5pt;
         background: """ + PALETTE.surface_alt + """; }
th { background: """ + PALETTE.background + """; text-align: left; font-weight: bold; }
.note { background: """ + PALETTE.warning_background + """;
        border-left: 3px solid """ + PALETTE.stale + """; padding: 7px 11px; margin: 9px 0; }
.warn { background: """ + PALETTE.error_background + """;
        border-left: 3px solid """ + PALETTE.error + """; padding: 7px 11px; margin: 9px 0; }
ul { margin: 5px 0 5px 18px; }
"""


# ---------------------------------------------------------------------------
# Die Kapitel liegen als Dateien daneben
# ---------------------------------------------------------------------------
#
# Bis Oktober 2026 standen die sieben Kapitel als Zeichenkettenkonstanten in
# dieser Datei: 890 der 1160 Zeilen waren HTML. Eine Datei, die zu drei
# Vierteln Text ist, liest sich nicht mehr als Modul, und jede Korrektur an
# einem Satz brauchte einen Eingriff in den Quelltext.
#
# Prosa war der Text allerdings nie. In ihm steckten 46 Formelbloecke und 22
# Quelltextverweise, aufgerufen und mit Pluszeichen zusammengesetzt:
#
#     _PALLET = """...""" + _source("app/palette/stapel.py", "analyze()") + """..."""
#
# Die beiden Funktionen bleiben deshalb, und die Dateien rufen sie ueber zwei
# Marken auf:
#
#     <<formel
#     F_halt = n_wirksam * F_sauger * mu
#     >>
#     <<quelle app/palette/stapel.py | analyze()>>
#
# Die Maskierung von _formula() ist nicht Verzierung: ein Vergleich wie
# "pi <= pi_krit" zerlegt sonst das ganze Dokument, weil die Anzeige das
# Kleinerzeichen als Beginn eines HTML-Elements liest und alles bis zum
# naechsten groesser-als verschluckt. Genau deshalb steht die Formel als Marke
# in der Datei und nicht als fertiges HTML: wer einen Satz aendert, soll die
# Maskierung nicht von Hand nachziehen muessen.

#: Ordner mit den Kapiteltexten. Er liegt NEBEN dieser Datei und wird ueber
#: __file__ gefunden - wie darkstyle/ und icons/ auch, und aus demselben
#: Grund: PyInstaller legt mitgelieferte Dateien unter demselben relativen
#: Pfad ab (siehe --add-data in AUTOBUILD.py), und __file__ zeigt dort in das
#: entpackte Verzeichnis.
#:
#: Zieht diese Datei um, zieht der Ordner mit.
HILFETEXTE_DIRNAME = "hilfetexte"


def hilfetexte_dir() -> Path:
    """Der Ordner hilfetexte/ neben dieser Datei."""
    return Path(__file__).resolve().parent / HILFETEXTE_DIRNAME


#: Eine Marke: <<formel ...>> oder <<quelle pfad | detail>>.
_MARKE = re.compile(r"<<(formel|quelle)\s(.*?)>>", re.DOTALL)

#: Trennt Pfad und Erklaerung in einer Quellmarke.
_QUELLTRENNER = " | "


def _loese_marke(treffer: re.Match[str]) -> str:
    art, inhalt = treffer.group(1), treffer.group(2)
    if art == "formel":
        # Genau einen Umbruch vorn und hinten wegnehmen - die gehoeren zur
        # Marke und nicht zur Formel. strip() waere falsch: eine Leerzeile
        # INNERHALB eines Formelblocks ist gewollt und soll bleiben.
        koerper = inhalt.removeprefix("\n").removesuffix("\n")
        return _formula(*koerper.split("\n"))

    pfad, _, detail = inhalt.partition(_QUELLTRENNER)
    return _source(pfad, detail)


def _lies_kapitel(datei: Path) -> Section:
    """Ein Kapitel aus seiner Datei.

    Die erste Zeile traegt den Titel, die Sprungmarke steckt im Dateinamen
    hinter der Nummer: 03-pallet.html wird zu Section("pallet", ...). Eine
    eigene Inhaltsdatei daneben waere eine zweite Stelle, an der die
    Reihenfolge steht - und damit eine, die nicht mitgepflegt wird.
    """
    roh = datei.read_text(encoding="utf-8")
    kopf, umbruch, koerper = roh.partition("\n")
    if not umbruch or not kopf.startswith("titel:"):
        raise ValueError(
            str(datei) + ": die erste Zeile muss 'titel: ...' sein, nicht "
            + repr(kopf[:40])
        )
    _nummer, _strich, marke = datei.stem.partition("-")
    if not marke:
        raise ValueError(
            str(datei) + ": der Dateiname braucht die Form 01-marke.html"
        )
    return Section(marke, kopf[len("titel:"):].strip(),
                   _MARKE.sub(_loese_marke, koerper))


@lru_cache(maxsize=1)
def sections() -> tuple[Section, ...]:
    """Alle Kapitel in Anzeigereihenfolge.

    Die Reihenfolge ist die der Dateinamen - 01- bis 07-. Gemerkt wird das
    Ergebnis, weil der Dialog und full_document() es mehrfach brauchen und es
    sich zur Laufzeit nicht aendert; vorher war es eine Konstante und kostete
    auch nichts.
    """
    ordner = hilfetexte_dir()
    dateien = sorted(ordner.glob("*.html"))
    if not dateien:
        raise FileNotFoundError(
            "Keine Hilfetexte in " + str(ordner) + ". Im gepackten Betrieb "
            "fehlt dann der --add-data-Eintrag in AUTOBUILD.py."
        )
    return tuple(_lies_kapitel(d) for d in dateien)


def full_document() -> str:
    """Alle Kapitel als ein HTML-Dokument, mit Sprungmarken."""
    body = "\n".join(
        '<a name="' + section.anchor + '"></a>' + section.html
        for section in sections()
    )
    return "<html><head><style>" + STYLE + "</style></head><body>" + body + "</body></html>"


# ---------------------------------------------------------------------------
# formula_dialog.py
# ---------------------------------------------------------------------------
"""Fenster mit der Rechenwegdokumentation.

Kein modaler Dialog: man liest die Erklaerung, waehrend man die zugehoerigen
Werte im Tab danebenstehen hat. Ein modales Fenster wuerde genau das
verhindern.

Aufbau links Kapitelliste, rechts Text - bei sieben Kapiteln mit Formeln ist
eine reine Scrollflaeche nicht mehr zu ueberblicken. Dazu eine Suche, weil man
in so einem Text meist einen bestimmten Begriff sucht und nicht ein Kapitel.
"""

class FormulaHelpDialog(QDialog):
    """Erklaert jede Rechnung der Anwendung - mathematisch und im Quelltext."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rechenwege und Formeln")
        self.setModal(False)
        self.resize(1060, 780)

        self._sections = sections()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addLayout(self._build_search())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_index())
        splitter.addWidget(self._build_view())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 810])
        layout.addWidget(splitter, stretch=1)

        # Ein HaloButton und kein QDialogButtonBox - warum, steht beim
        # ProblemPanel in app/oberflaeche/meldungen.py, wo dieselbe Zeile
        # stand. Die Fussleiste schiebt ihn nach rechts, wohin der Kasten ihn
        # von sich aus gestellt hat.
        close = HaloButton("Schliessen")
        close.clicked.connect(self.reject)
        fussleiste = QHBoxLayout()
        fussleiste.addStretch(1)
        fussleiste.addWidget(close)
        layout.addLayout(fussleiste)

        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        self._index.setCurrentRow(0)

    # Aufbau -------------------------------------------------------------------

    def _build_search(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Suchen"))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Begriff eingeben, Eingabetaste fuer den naechsten Treffer")
        self._search.returnPressed.connect(self._find_next)
        self._search.textChanged.connect(self._on_search_changed)
        row.addWidget(self._search, stretch=1)

        next_button = HaloButton("Weiter")
        next_button.clicked.connect(self._find_next)
        row.addWidget(next_button)

        self._search_state = QLabel("")
        self._search_state.setStyleSheet("color: " + PALETTE.text_muted + ";")
        self._search_state.setMinimumWidth(150)
        row.addWidget(self._search_state)
        return row

    def _build_index(self) -> QWidget:
        self._index = QListWidget()
        self._index.addItems([section.title for section in self._sections])
        self._index.currentRowChanged.connect(self._on_section_selected)
        return self._index

    def _build_view(self) -> QWidget:
        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(False)
        self._view.setHtml(full_document())
        return self._view

    # Bedienung ----------------------------------------------------------------

    def _on_section_selected(self, row: int) -> None:
        if 0 <= row < len(self._sections):
            self._view.scrollToAnchor(self._sections[row].anchor)

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _on_search_changed(self, text: str) -> None:
        """Bei jeder Eingabe von vorn suchen.

        Ohne das Zuruecksetzen der Schreibmarke sucht Qt ab der aktuellen
        Stelle weiter, und ein neuer Begriff wird im Text darueber nicht
        gefunden - was aussieht, als gaebe es ihn nicht.
        """
        self._search_state.setText("")
        if not text:
            return
        cursor = self._view.textCursor()
        cursor.setPosition(0)
        self._view.setTextCursor(cursor)
        self._find_next()

    def _find_next(self) -> None:
        text = self._search.text().strip()
        if not text:
            return
        if self._view.find(text):
            self._search_state.setText("")
            return

        # Nichts mehr ab der aktuellen Stelle: von vorn versuchen, bevor
        # "nicht gefunden" gemeldet wird.
        cursor = self._view.textCursor()
        cursor.setPosition(0)
        self._view.setTextCursor(cursor)
        if self._view.find(text):
            self._search_state.setText("wieder von vorn")
        else:
            self._search_state.setText("nicht gefunden")

    def show_section(self, anchor: str) -> None:
        """Ein bestimmtes Kapitel aufschlagen - fuer einen spaeteren
        Direkteinstieg aus einem Tab heraus."""
        for row, section in enumerate(self._sections):
            if section.anchor == anchor:
                self._index.setCurrentRow(row)
                return

    def find_in_document(self, text: str) -> bool:
        """Suche von aussen anstossen. Gibt zurueck, ob etwas gefunden wurde."""
        document = self._view.document()
        return not document.find(text, 0, QTextDocument.FindFlag(0)).isNull()
