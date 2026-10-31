"""Erzwingt die Schichtdisziplin (Spezifikation 10 und 38).

Dokumentierte Regeln erodieren. Ein einziger bequemer Import aus der
Oberflaeche in eine Engine faellt in keiner Codepruefung auf und macht die
Schicht wertlos. Geprueft wird deshalb der Quelltext per AST - ein verbotener
Import faellt damit auch dann auf, wenn der betroffene Zweig nie laeuft.

Die Datenflussrichtung:

    core  <-  dto  <-  engines
      ^        ^          ^
      |        |          |
      +--- config --------+
      |        |
      +--- services  <-  jobs
               ^
               |
    visualization  <-  gui

Kurz: jede Schicht darf nur nach unten greifen, nie nach oben.
"""

from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


# Paket -> Praefixe, die es NICHT importieren darf.
#
# Zwei Schnitte liegen uebereinander, und sie meinen Verschiedenes.
#
# SENKRECHT schneiden app/palette/ und app/vakuum/: je ein Gegenstand, in sich
# vollstaendig. Was ein Modul darin darf, sagt sein NAME und nicht sein Ordner
# - eine rechnung.py ist in jeder Scheibe eine rechnung.py. Siehe ROLLEN.
#
# WAAGERECHT liegen app/oberflaeche/, app/fach/ und app/technik/ darunter.
# Das ist nicht die Rueckkehr der alten Schichten (core, dto, engines,
# services, visualization, gui): die schnitten quer durch den Gegenstand, und
# ein einziges Merkmal lag in sieben Ordnern. Diese drei tragen gar keinen
# Gegenstand - sie sind der Werkzeugkasten, der Gemeinbesitz und der Unterbau.
# Die Pruefrage lautet: fasst ein neues Merkmal mehr Ordner an als vorher?
# Eine dritte Scheibe waere app/<name>/ plus eine Zeile in app/tabs.py.
#
# In der Wurzel von app/ liegt das Programm selbst - __main__, start, tabs,
# kontext. Fuenf Dateien, kein Paket: es ist die Stelle, an der die Teile
# zusammenkommen, und die hat keine Schichtregel ueber sich.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    # Die beiden Scheiben kennen einander nicht. Was beide brauchen, steht in
    # app/fach/ - deshalb liegt legemuster.py dort und nicht bei der Palette.
    "palette": ("app.vakuum",),
    "vakuum": ("app.palette",),

    # Der Werkzeugkasten kennt keinen Gegenstand.
    #
    # Das ist die scharfste Regel im Programm und die nuetzlichste: sie ist
    # der Grund, warum sich der Inhalt dieses Pakets ueberhaupt in eine
    # Bibliothek heben laesst. Ein einziger Import aus app.fach hier - und sei
    # es nur fuer eine Typangabe - macht aus einem Bedienelement ein
    # TRXing-Bedienelement.
    "oberflaeche": ("app.palette", "app.vakuum", "app.fach",
                    "app.start", "app.tabs", "app.kontext"),

    # Das Fach weiss nichts von der Anzeige und nichts vom Zusammenbau.
    #
    # Die Scheiben fehlen hier bewusst: katalog.py liest die JSON-Kataloge in
    # die Datenobjekte beider Scheiben ein und muss sie dafuer kennen. Wie
    # weit das reicht, steht nicht hier, sondern in
    # test_the_subject_layer_reaches_into_the_slices_only_for_their_data -
    # eine Praefixliste koennte "nur daten.py" nicht ausdruecken.
    "fach": ("app.oberflaeche", "app.start", "app.tabs", "app.kontext"),

    # Die unterste Lage greift nach nichts.
    #
    # Hintergrundarbeit, Protokoll, Verzeichnisse. Sobald ein Modul hier nach
    # oben greift, ist die Lage keine Lage mehr und die Testsuite verliert
    # ihren Grund, ohne QApplication zu laufen.
    "technik": ("app.oberflaeche", "app.fach", "app.palette", "app.vakuum",
                "app.start", "app.tabs", "app.kontext"),
}


#: Ringe zwischen Paketen, die bestehen - mit Grund und mit Heilmittel.
#:
#: Jeder Eintrag ist eine Ausnahme, die jemand aufgeschrieben und begruendet
#: hat. Ein NEUER Ring faellt weiterhin auf. Der Unterschied zu einem
#: abgeschalteten Test ist genau dieser: hier steht, was der Ring kostet und
#: was ihn aufloest.
RINGE_MIT_GRUND: dict[str, str] = {
    # Eine Ursache, zwei Eintraege.
    "fach <-> palette":
        "app/fach/katalog.py liest die JSON-Kataloge in app.palette.daten ein. "
        "Aufloesen wuerde: katalog.py zerlegen und das Einlesen je Scheibe in "
        "deren eigenes Modul geben.",
    "fach <-> vakuum":
        "Dasselbe fuer app.vakuum.daten - siehe 'fach <-> palette'.",

    # Eine Ursache, zwei Eintraege.
    "(programm) <-> palette":
        "app/tabs.py und app/kontext.py sind Vertrag UND Registratur in einer "
        "Datei: die Scheibe holt sich TabHost und AppContext, und dieselben "
        "Dateien fuehren die Liste der Module. Aufloesen wuerde: den Vertrag "
        "vom Zusammenbau trennen. Kostet aber die scharfe Regel fuer "
        "app/oberflaeche/, denn TabHost braucht app.fach.vorgang - deshalb "
        "steht es bewusst noch so.",
    "(programm) <-> vakuum":
        "Dasselbe fuer die zweite Scheibe - siehe '(programm) <-> palette'.",
}


#: Module, die unter keinen Umstaenden Qt importieren duerfen.
#:
#: Sie sind der Grund, warum die Testsuite in Sekunden statt Minuten laeuft:
#: der Grossteil der Tests braucht keine QApplication. Ein einziger
#: Qt-Import an der falschen Stelle kippt das, ohne dass sofort etwas
#: auffaellt - deshalb diese Liste.
QT_FREE = (
    "einheiten.py", "ergebnis.py", "fehler.py", "pfade.py", "katalog.py",
    "vorgang.py", "geometrie.py", "paket.py", "legemuster.py",
    "daten.py", "rechnung.py", "stapel.py", "physik.py", "anordnung.py",
    "saugermuster.py",
)


#: Wer was darf - nach dem Namen des Moduls, nicht nach seinem Ordner.
#:
#: In einer Schichtenarchitektur sagte der ORDNER, was ein Modul darf. Bei
#: vertikalen Schnitten liegt alles zu einem Thema beieinander, und der Ordner
#: sagt nur noch, WORUM es geht. Die Rolle steckt im Dateinamen - und der ist
#: in jeder Scheibe derselbe: eine rechnung.py ist ueberall eine rechnung.py.
ROLLEN: dict[str, tuple[str, ...]] = {
    # Rechnen. Kein Qt, keine Dateien, keine Oberflaeche.
    "rechnend": QT_FREE,

    # Zeichnen. Stellt dar, was im Ergebnis steht, und entscheidet nichts.
    "zeichnend": ("zeichnung.py", "szene3d.py"),

    # Bedienen. Nimmt entgegen und zeigt an; gerechnet wird hinter der Tuer,
    # die dienst.py aufmacht. Bewusst NUR die beiden Tab-Module: dienst.py
    # gehoert zur Oberflaeche, darf die Rechnung aber anstossen.
    "bedienend": ("tab.py", "formular.py"),

    # Die Oberflaeche im weiteren Sinn - alles, was Qt anfasst, ohne zu
    # zeichnen. Fuer die Regel "hier wird nicht gerechnet" ist das der
    # richtige Umfang: frueher war es der ganze Ordner app/gui.
    #
    # bedienelemente.py fehlt seit Oktober 2026: die Bedienelemente selbst
    # liegen als compact.py in qt_controls_pyrs, wo mehrere Anwendungen sie
    # teilen. Was sie an Regeln brauchen, prueft die Bibliothek.
    #
    # formularbau.py, fensterzustand.py und entprellung.py lagen kurzzeitig
    # ebenfalls dort und sind zurueckgekommen: eine Widget-Sammlung bestimmt
    # das AUSSEHEN eines Programms. Ein Formularbau legt fest, WAS wo steht,
    # der Fensterzustand haelt Zustand, die Entprellung bremst Signale -
    # nichts davon ist ein Bedienelement. Siehe doc/ARCHITECTURE.md.
    "oberflaeche": ("tab.py", "formular.py", "dienst.py", "start.py",
                    "tabs.py", "kontext.py", "rechenlauf.py",
                    "meldungen.py", "hilfe.py", "darstellung.py",
                    "formularbau.py", "fensterzustand.py", "entprellung.py"),

    # Datentragend. Eingefrorene Objekte mit Einheitensuffix, kein Verhalten.
    #
    # geometrie.py steht mit drin, seit dto/common.py aufgeteilt ist - Rect2D
    # und Footprint sind Datentypen wie zuvor. ergebnis.py dagegen NICHT: dort
    # steht neben CalculationMeta auch CalculationTrace, und das ist ein
    # Sammler, der waehrend der Rechnung waechst. Veraenderlich zu sein ist
    # seine Aufgabe, nicht sein Fehler.
    "daten": ("daten.py", "paket.py", "geometrie.py"),
}

#: Die Rechenteile, in die die Oberflaeche nicht hineingreifen darf.
#:
#: daten.py fehlt hier bewusst: die Datenobjekte sind das, WAS angezeigt wird.
#: dienst.py ebenfalls - es ist die Tuer. Alles uebrige ist Rechnung, und wer
#: von einem Tab aus direkt hineinfasst, baut die Fachlogik in die Anzeige.
RECHENTEILE = ("rechnung.py", "physik.py", "anordnung.py", "stapel.py",
               "saugermuster.py", "legemuster.py", "geometrie.py")

#: Module, die auf Dateien zugreifen DUERFEN - und zwar nur diese drei.
#:
#: katalog.py liest die JSON-Kataloge, pfade.py sagt wo sie liegen, und
#: fehler.py legt die Protokolldatei an. Alles andere bekommt gereicht, was es
#: braucht.
DATEIZUGRIFF_ERLAUBT = ("katalog.py", "pfade.py", "fehler.py")


def _rolle(name: str) -> list[pathlib.Path]:
    """Alle Module einer Rolle, quer ueber die Scheiben."""
    return sorted(
        p for p in APP.rglob("*.py")
        if p.name in ROLLEN[name] and "__pycache__" not in p.parts
    )


def _imports_of(path: pathlib.Path) -> list[tuple[str, int]]:
    """Alle importierten Modulnamen einer Datei mit Zeilennummer."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module, node.lineno))
    return found


def _python_files(package: str) -> list[pathlib.Path]:
    return sorted(p for p in (APP / package).rglob("*.py") if "__pycache__" not in p.parts)


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(APP.parent)).replace("\\", "/")


# Importrichtung ---------------------------------------------------------------

@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_layer_does_not_import_upwards(package: str) -> None:
    forbidden = FORBIDDEN[package]
    violations: list[str] = []

    for path in _python_files(package):
        for module, line in _imports_of(path):
            for prefix in forbidden:
                if module == prefix or module.startswith(prefix + "."):
                    violations.append(_relative(path) + ":" + str(line) + " -> " + module)

    assert not violations, (
        "app/" + package + " verletzt die Datenflussrichtung:\n  " + "\n  ".join(violations)
    )


def test_the_interface_does_not_reach_into_the_calculation() -> None:
    """Ein Tab zeigt an - gerechnet wird hinter der Tuer.

    Frueher sicherte das die Serviceschicht: die Oberflaeche kam an die Engine
    gar nicht heran. Bei vertikalen Schnitten liegt beides im selben Ordner,
    und der Griff ist nur noch eine Zeile weit. Deshalb diese Regel.

    Erlaubt bleiben daten.py - die Datenobjekte sind das, was angezeigt wird -
    und dienst.py, das die Rechnung im Hintergrund anstoesst. Verboten ist der
    direkte Zugriff auf rechnung, physik, anordnung, stapel und die Muster.

    Gemessener Zustand zum Zeitpunkt des Umbaus: kein einziger Verstoss. Die
    Regel haelt ihn fest, statt ihn dem Zufall zu ueberlassen.
    """
    violations: list[str] = []
    for path in _rolle("bedienend"):
        for module, line in _imports_of(path):
            letzter = module.rsplit(".", 1)[-1] + ".py"
            if letzter in RECHENTEILE:
                violations.append(_relative(path) + ":" + str(line) + " -> " + module)

    assert not violations, (
        "Die Oberflaeche greift direkt in die Rechnung: " + ", ".join(violations)
    )


# Dateizugriffe ----------------------------------------------------------------

def _calls_named(path: pathlib.Path, names: set[str]) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = target.id if isinstance(target, ast.Name) else (
            target.attr if isinstance(target, ast.Attribute) else ""
        )
        if name in names:
            found.append((name, node.lineno))
    return found


def test_the_calculating_modules_do_not_touch_the_filesystem() -> None:
    """Spezifikation 04: gerechnet wird mit dem, was hereingereicht wird.

    Alles, was eine Rechnung braucht, kommt als Datenobjekt herein. Ohne diese
    Regel wandert die Konfiguration nach und nach in die Fachlogik, und die
    Rechnung ist ohne Dateisystem nicht mehr pruefbar.

    Ausgenommen sind katalog.py und pfade.py - Dateien lesen ist ihre Aufgabe.
    """
    violations: list[str] = []
    for path in _rolle("rechnend"):
        if path.name in DATEIZUGRIFF_ERLAUBT:
            continue
        for module, line in _imports_of(path):
            if module in ("json", "pathlib", "csv", "configparser", "sqlite3", "shutil", "os.path"):
                violations.append(_relative(path) + ":" + str(line) + " -> " + module)
        for name, line in _calls_named(path, {"open", "read_text", "write_text"}):
            violations.append(_relative(path) + ":" + str(line) + " -> " + name + "()")

    assert not violations, "Engines greifen auf Dateien zu:\n  " + "\n  ".join(violations)


def test_configuration_is_read_in_exactly_one_module() -> None:
    """Spezifikation 27: json.load steht in katalog.py und sonst nirgends.

    Frueher sicherte das ein eigener Ordner app/config. Den gibt es nicht
    mehr, die Regel schon: wer anderswo eine JSON-Datei aufmacht, baut einen
    zweiten Weg in die Konfiguration, der die Pruefungen des ersten nicht
    kennt.
    """
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "katalog.py" or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # Geprueft wird der LESENDE Aufruf, nicht der Import. app/__main__.py
            # gibt mit --json einen Statusbericht aus; Schreiben ist erlaubt,
            # Lesen nicht. Der blosse Import sagt darueber nichts.
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            ziel = node.func
            if (isinstance(ziel.value, ast.Name) and ziel.value.id == "json"
                    and ziel.attr in ("load", "loads")):
                violations.append(_relative(path) + ":" + str(node.lineno)
                                  + " -> json." + ziel.attr + "()")

    assert not violations, "Konfiguration wird ausserhalb von katalog.py gelesen: " + ", ".join(violations)


# Fachlogik in der Oberflaeche -------------------------------------------------

def test_gui_contains_no_calculation_formulas() -> None:
    """Spezifikation 10: keine Berechnungsformeln in der Oberflaeche.

    Als Anhaltspunkt dient der Import von Rechenbibliotheken. Die Oberflaeche
    darf Werte umrechnen (app.fach.einheiten) und formatieren, aber nicht rechnen.
    Wer hier math oder numpy braucht, baut gerade eine Formel nach, die in eine
    Engine gehoert.
    """
    violations = [
        _relative(path) + ":" + str(line) + " -> " + module
        for path in _rolle("oberflaeche")
        for module, line in _imports_of(path)
        if module in ("math", "numpy", "scipy", "statistics") or module.startswith(("numpy.", "scipy."))
    ]
    assert not violations, "Rechenbibliothek in der Oberflaeche:\n  " + "\n  ".join(violations)


def test_renderers_contain_no_business_logic() -> None:
    """Spezifikation 37: die Darstellung entscheidet nichts.

    Ob ein Sauger wirksam ist oder ein Paket ueberlastet, steht im Ergebnis.
    Ein Renderer, der die Geometriehilfen der Engine importiert, faengt gerade
    an, es selbst zu entscheiden.
    """
    violations = [
        _relative(path) + ":" + str(line) + " -> " + module
        for path in _rolle("zeichnend")
        for module, line in _imports_of(path)
        if module.rsplit(".", 1)[-1] + ".py" in RECHENTEILE
    ]
    assert not violations, "Fachlogik in der Darstellung:\n  " + "\n  ".join(violations)


# Modulvertrag -----------------------------------------------------------------

def test_registered_modules_satisfy_the_contract() -> None:
    """Spezifikation 06: neue Module muessen dem Modulvertrag entsprechen."""
    from app.tabs import CalculationModule, default_modules

    for module in default_modules():
        assert isinstance(module, CalculationModule), (
            type(module).__name__ + " erfuellt den Modulvertrag nicht"
        )
        assert module.module_id and isinstance(module.module_id, str)
        assert module.title and isinstance(module.title, str)
        assert isinstance(module.order, int)


def test_module_ids_are_unique() -> None:
    from app.tabs import default_modules

    ids = [module.module_id for module in default_modules()]
    assert len(ids) == len(set(ids)), "Doppelte Modulkennung: " + str(ids)


def test_registry_rejects_a_module_without_the_contract() -> None:
    from app.tabs import ModuleRegistry

    class NotAModule:
        pass

    with pytest.raises(TypeError):
        ModuleRegistry().register(NotAModule())


def test_main_window_names_no_module() -> None:
    """Spezifikation 06: kein Code im Hauptfenster ist auf 'Tab 2' zugeschnitten.

    Geprueft wird, dass der Zusammenbau keine Modulkennung als Zeichenkette
    enthaelt - genau so entstehen die verbotenen Sonderbehandlungen.

    Geprueft wird app/start.py, wo seit dem Umbau Application und MainWindow
    stehen. Die Modulliste selbst nennt die Kennungen natuerlich; sie steht
    deshalb in app/tabs.py und ausdruecklich nicht hier.
    """
    from app.tabs import default_modules

    source = (APP / "start.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    named = {m.module_id for m in default_modules()} & literals
    assert not named, "Das Hauptfenster nennt Module beim Namen: " + str(named)


# Einheiten an DTO-Feldern ------------------------------------------------------

def _dataclass_fields(path: pathlib.Path):
    """Alle annotierten Felder der Dataclasses einer Datei."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                annotation = ast.unparse(statement.annotation)
                yield node.name, statement.target.id, annotation, statement.lineno


#: Felder, die eine Zahl tragen, aber keine feste physikalische Einheit haben.
#:
#: Die Zaehler und Kennungen sind offensichtlich einheitenlos.
#:
#: permeability_value ist die begruendete Ausnahme: seine Einheit haengt vom
#: gewaehlten Leckagemodell ab - je Sauger, je Flaeche, oder je Flaeche und
#: Druck (siehe app/vakuum/physik.py). Ein fester Suffix waere fuer
#: drei der vier Modelle falsch. Die Einheit wird deshalb im Feld unit_label
#: mitgefuehrt und in der Oberflaeche neben dem Eingabefeld angezeigt. Genau
#: das verlangt Spezifikation 22: die Permeabilitaet ist keine Naturkonstante,
#: sondern ein Modellparameter.
_UNITLESS_FIELDS = {
    "index", "package_index", "layer_index", "placement_index", "row_index",
    "column_index", "request_id", "state_revision", "revision", "version",
    "permeability_value",
}


def test_numeric_dto_fields_carry_a_unit_suffix() -> None:
    """Die Einheitenkonvention aus app/fach/einheiten.py, maschinell geprueft.

    Eine Vakuumrechnung mischt mbar, l/min, m3/h, N, kg und mm. Wer das ohne
    feste Konvention rechnet, produziert Ergebnisse, die um Faktor 60 oder 1000
    danebenliegen und trotzdem plausibel aussehen. Der Suffix macht den Fehler
    schon beim Lesen sichtbar.
    """
    from app.fach.einheiten import FIELD_SUFFIXES

    violations: list[str] = []
    for path in _rolle("daten"):
        for class_name, field, annotation, line in _dataclass_fields(path):
            if field in _UNITLESS_FIELDS or field.startswith("_"):
                continue
            base = annotation.replace(" ", "").split("|")[0]
            if base not in ("float", "int"):
                continue
            if not any(field.endswith(suffix) for suffix in FIELD_SUFFIXES):
                violations.append(
                    _relative(path) + ":" + str(line) + " " + class_name + "." + field + ": " + annotation
                )

    assert not violations, (
        "Numerische DTO-Felder ohne Einheitensuffix (erlaubt sind "
        + ", ".join(FIELD_SUFFIXES) + "):\n  " + "\n  ".join(violations)
    )


def test_dtos_are_frozen() -> None:
    """Spezifikation 28: DTOs sind unveraenderlich.

    Ein veraenderliches Ergebnis-DTO waere ein Einfallstor: die Oberflaeche
    koennte einen Wert nachbessern, und niemand saehe, dass die angezeigte Zahl
    nicht mehr die der Engine ist.
    """
    violations: list[str] = []
    for path in _rolle("daten"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any("dataclass" in d for d in decorators):
                continue
            if not any("frozen=True" in d for d in decorators):
                violations.append(_relative(path) + ":" + str(node.lineno) + " " + node.name)

    assert not violations, "Veraenderliche DTOs:\n  " + "\n  ".join(violations)


# Vollstaendigkeit --------------------------------------------------------------

def test_every_package_is_covered_by_a_rule() -> None:
    """Ein neues Unterpaket ohne Regel wuerde stillschweigend alles duerfen."""
    packages = {
        p.name for p in APP.iterdir()
        if p.is_dir() and not p.name.startswith("__")
    }
    uncovered = packages - set(FORBIDDEN)
    assert not uncovered, (
        "Diese Pakete haben keine Schichtregel in FORBIDDEN: " + ", ".join(sorted(uncovered))
    )


#: Name der Wurzel von app/ im Ringtest. Sie ist kein Paket, traegt aber
#: Abhaengigkeiten wie eines - und wurde deshalb vorher nicht geprueft.
PROGRAMM = "(programm)"


def _paketkanten() -> dict[str, set[str]]:
    """Welches Paket von welchem abhaengt. Die Wurzel zaehlt als eines mit.

    Gezaehlt werden auch Importe INNERHALB von Funktionen. app/tabs.py holt
    die beiden Tab-Klassen erst dort, damit beim Laden kein Ring entsteht -
    fuer die Frage, wer von wem abhaengt, aendert das nichts.
    """
    def paket_von(pfad: pathlib.Path) -> str:
        teile = pfad.relative_to(APP).parts
        return teile[0] if len(teile) > 1 else PROGRAMM

    kanten: dict[str, set[str]] = {}
    for pfad in sorted(APP.rglob("*.py")):
        if "__pycache__" in pfad.parts:
            continue
        quelle = paket_von(pfad)
        ziele = kanten.setdefault(quelle, set())
        for modul, _zeile in _imports_of(pfad):
            if not modul.startswith("app."):
                continue
            teil = modul.split(".")[1]
            ziel = teil if (APP / teil).is_dir() else PROGRAMM
            if ziel != quelle:
                ziele.add(ziel)
    return kanten


def test_no_module_imports_itself_in_a_circle() -> None:
    """Spezifikation 01: keine zyklischen Abhaengigkeiten.

    Geprueft auf Paketebene - ein Zyklus innerhalb eines Pakets ist eine
    Geschmacksfrage, einer zwischen Paketen ein Architekturfehler.

    Seit die Wurzel von app/ gruppiert ist, prueft dieser Test MEHR als
    vorher: die vier Pakete darunter und zusaetzlich die Wurzel selbst. Als
    alles flach in app/ lag, waren Zweiwege-Abhaengigkeiten zwischen
    Werkzeugkasten, Fach und Zusammenbau unsichtbar - nicht, weil es sie nicht
    gab, sondern weil sie alle im selben Ordner lagen.

    Vier davon sind dabei zum Vorschein gekommen. Sie stehen mit Grund und
    Heilmittel in RINGE_MIT_GRUND und nicht in einem auskommentierten Test.
    """
    kanten = _paketkanten()

    ringe: list[str] = []
    for quelle, ziele in kanten.items():
        for ziel in ziele:
            if quelle in kanten.get(ziel, set()):
                paar = " <-> ".join(sorted((quelle, ziel)))
                if paar not in ringe:
                    ringe.append(paar)

    neu = sorted(set(ringe) - set(RINGE_MIT_GRUND))
    assert not neu, (
        "Neue zyklische Paketabhaengigkeiten:\n  " + "\n  ".join(neu)
        + "\n\nEntweder aufloesen oder mit Grund in RINGE_MIT_GRUND eintragen."
    )


def test_every_documented_ring_still_exists() -> None:
    """Eine Ausnahme, die niemand mehr braucht, muss verschwinden.

    Ohne diesen Test waechst RINGE_MIT_GRUND nur noch: wer einen Ring
    aufloest, merkt nicht, dass die Begruendung dafuer noch dasteht - und der
    naechste liest sie als geltende Architektur.
    """
    kanten = _paketkanten()

    vorhanden = set()
    for quelle, ziele in kanten.items():
        for ziel in ziele:
            if quelle in kanten.get(ziel, set()):
                vorhanden.add(" <-> ".join(sorted((quelle, ziel))))

    veraltet = sorted(set(RINGE_MIT_GRUND) - vorhanden)
    assert not veraltet, (
        "Diese Ringe gibt es nicht mehr - Eintrag aus RINGE_MIT_GRUND "
        "entfernen:\n  " + "\n  ".join(veraltet)
    )


def test_the_subject_layer_reaches_into_the_slices_only_for_their_data() -> None:
    """Das Fach darf aus einer Scheibe nur deren Datenobjekte holen.

    app/fach/katalog.py liest die JSON-Kataloge in PalletSpec, SuctionCupSpec
    und ihre Nachbarn ein und muss diese Typen deshalb kennen. Mehr nicht:
    griffe es nach app.palette.rechnung oder app.vakuum.dienst, waere aus dem
    Gemeinbesitz ein Teilnehmer geworden, und die Scheiben haetten eine Lage
    unter sich, die sie kennt.

    Eine Praefixliste in FORBIDDEN kann das nicht ausdruecken - "app.palette"
    verbietet alles oder nichts.
    """
    verstoesse: list[str] = []
    for pfad in _python_files("fach"):
        for modul, zeile in _imports_of(pfad):
            for scheibe in ("app.palette", "app.vakuum"):
                if modul.startswith(scheibe + ".") and not modul.endswith(".daten"):
                    verstoesse.append(
                        _relative(pfad) + ":" + str(zeile) + " -> " + modul
                    )
    assert not verstoesse, (
        "Das Fach greift tiefer als daten.py in eine Scheibe: "
        + ", ".join(verstoesse)
    )


def test_the_calculating_modules_stay_qt_free() -> None:
    """Die rechnenden Module duerfen Qt nicht kennen.

    Nicht aus Reinheit, sondern aus Geschwindigkeit: von den Tests laeuft der
    Grossteil ohne QApplication, und das geht nur, solange die Rechnung keine
    mitzieht. Ein einziger Import an der falschen Stelle macht aus einer
    Sekunde eine Minute - und faellt sonst erst auf, wenn die Suite schon
    unertraeglich langsam ist.

    Geprueft werden Module nach ihrem NAMEN, quer ueber alle Scheiben: eine
    rechnung.py ist in jeder Scheibe eine rechnung.py.
    """
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name not in QT_FREE:
            continue
        for module, line in _imports_of(path):
            if module.split(".")[0] in ("PyQt6", "PySide6", "PyQt5", "qtpy"):
                offenders.append(
                    str(path.relative_to(APP.parent)) + ":" + str(line) + " -> " + module
                )
    assert not offenders, (
        "Diese rechnenden Module importieren Qt: " + ", ".join(offenders)
    )


# Namen, die es nicht gibt --------------------------------------------------

#: Was in jedem Modul bekannt ist, ohne dass es dort steht.
_EINGEBAUT = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__class__",
}


def _gebundene_namen(baum: ast.AST) -> set[str]:
    """Alle Namen, die eine Datei irgendwo bindet.

    Grosszuegig gezaehlt und ueber alle Ebenen hinweg: eine Variable, die nur
    in einer Funktion zugewiesen wird, gilt auch im Dateikopf als bekannt. Das
    ist absichtlich zu nachsichtig. Eine genaue Namensaufloesung waere ein
    halbes pyflakes; was hier gesucht wird, ist der Name, den es NIRGENDS
    gibt.
    """
    namen: set[str] = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for alias in knoten.names:
                namen.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(knoten, ast.ImportFrom):
            for alias in knoten.names:
                namen.add(alias.asname or alias.name)
        elif isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            namen.add(knoten.name)
        elif isinstance(knoten, ast.arg):
            namen.add(knoten.arg)
        elif isinstance(knoten, ast.Name) and isinstance(knoten.ctx, (ast.Store, ast.Del)):
            namen.add(knoten.id)
        elif isinstance(knoten, ast.ExceptHandler) and knoten.name:
            namen.add(knoten.name)
        elif isinstance(knoten, (ast.Global, ast.Nonlocal)):
            namen.update(knoten.names)
        elif isinstance(knoten, (ast.MatchAs, ast.MatchStar)) and knoten.name:
            namen.add(knoten.name)
    return namen


@pytest.mark.parametrize("ordner", ["app", "tests", "."])
def test_no_module_uses_a_name_that_does_not_exist(ordner: str) -> None:
    """Ein Name, den es nirgends gibt, ist ein NameError beim Benutzen.

    Entstanden an einem echten Fall: beim Zurueckholen eines Moduls aus der
    Bibliothek hat eine Textersetzung APP_SLUG aus dem Import von
    app/__main__.py genommen, obwohl die Datei den Namen zwei Funktionen
    weiter benutzt. Die Anwendung startete nicht mehr - und alle 579 Tests
    blieben gruen, weil keiner von ihnen app/__main__.py anfasst.

    Der Import allein reicht als Schutz nicht: der Name steht INNERHALB einer
    Funktion, und die laeuft erst beim Start.

    "." sind die Dateien in der Projektwurzel, nicht rekursiv: main.py und
    AUTOBUILD.py. Dieselbe Ersetzung hat auch AUTOBUILD.py erwischt, und das
    waere erst beim naechsten Bauen der .exe aufgefallen.
    """
    wurzel = APP.parent / ordner
    dateien = wurzel.glob("*.py") if ordner == "." else wurzel.rglob("*.py")
    verstoesse: list[str] = []
    for pfad in sorted(dateien):
        if "__pycache__" in pfad.parts:
            continue
        baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
        bekannt = _gebundene_namen(baum) | _EINGEBAUT
        offen: dict[str, int] = {}
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Name) and isinstance(knoten.ctx, ast.Load)
                    and knoten.id not in bekannt):
                offen.setdefault(knoten.id, knoten.lineno)
        for name, zeile in sorted(offen.items(), key=lambda paar: paar[1]):
            verstoesse.append(_relative(pfad) + ":" + str(zeile) + " -> " + name)

    assert not verstoesse, (
        "Diese Namen gibt es in ihrer Datei nicht:\n  " + "\n  ".join(verstoesse)
    )


def test_the_program_starts_as_a_process() -> None:
    """Der Einstiegspunkt wird wirklich ausgefuehrt, nicht nur importiert.

    app/__main__.py war bis 2026-10-31 die einzige Datei des Programms, die
    kein Test je angefasst hat - ausgerechnet die, mit der es startet. Ein
    Fehler darin faellt sonst erst dem Benutzer auf.

    --version laeuft ohne Fenster und ohne Konfiguration durch; geprueft wird
    damit, dass das Modul laedt, argparse steht und der Prozess sauber endet.
    """
    import subprocess
    import sys

    wurzel = APP.parent
    ergebnis = subprocess.run(
        [sys.executable, "-m", "app", "--version"],
        cwd=str(wurzel), capture_output=True, text=True, timeout=120,
    )
    assert ergebnis.returncode == 0, (
        "python -m app --version endete mit " + str(ergebnis.returncode)
        + "\n" + ergebnis.stderr[-2000:]
    )
    assert "TRXing" in ergebnis.stdout, ergebnis.stdout
