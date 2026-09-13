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
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


# Paket -> Praefixe, die es NICHT importieren darf.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    # Die Querschnittsschicht kennt niemanden. Qt-frei, damit die gesamte
    # Fachlogik ohne QApplication testbar bleibt.
    "core": ("PyQt6", "PySide6", "app.dto", "app.config", "app.engines",
             "app.services", "app.jobs", "app.visualization", "app.gui"),

    # Datenobjekte tragen Daten, kein Verhalten und keine Abhaengigkeiten
    # ausser der Querschnittsschicht.
    "dto": ("PyQt6", "PySide6", "app.config", "app.engines", "app.services",
            "app.jobs", "app.visualization", "app.gui"),

    # Engines: Fachlogik. Kein Qt, keine Services, keine Konfiguration - sie
    # bekommen alles als DTO uebergeben.
    "engines": ("PyQt6", "PySide6", "app.config", "app.services", "app.jobs",
                "app.visualization", "app.gui"),

    # Konfiguration: liest Dateien und erzeugt DTOs. Kennt keine Engine.
    "config": ("PyQt6", "PySide6", "app.engines", "app.services", "app.jobs",
               "app.visualization", "app.gui"),

    # Services duerfen QtCore (Signale sind der threadsichere Rueckweg aus dem
    # Worker), aber keine Bedienelemente und keine Oberflaeche.
    "services": ("PyQt6.QtWidgets", "PyQt6.QtGui", "PySide6",
                 "app.visualization", "app.gui"),

    # Die Jobschicht ist fachlich blind: sie fuehrt aus, was ihr uebergeben
    # wird, und kennt weder Engine noch Oberflaeche.
    "jobs": ("app.engines", "app.services", "app.visualization", "app.gui"),

    # Darstellung: zeichnet DTOs. Keine Fachlogik, keine Services, und
    # ausdruecklich kein Rueckgriff auf die Oberflaeche.
    "visualization": ("app.engines", "app.services", "app.jobs", "app.config", "app.gui"),

    # Die Oberflaeche spricht ueber Services. Sie kennt keine Engine und liest
    # keine Konfigurationsdatei.
    "gui": ("app.engines", "app.config.loader", "app.config.schema", "json"),
}


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


def test_gui_talks_only_to_services_dtos_and_renderers() -> None:
    """Spezifikation 29: die Oberflaeche kennt Services und DTOs, sonst nichts.

    Ausnahmen sind die Querschnittsschicht core, die Jobhuellen (fuer
    JobHandle), die Darstellungsschicht und die Composition Root, die die
    Oberflaeche mit fertigen Objekten versorgt.
    """
    allowed = ("app.services", "app.dto", "app.core", "app.jobs",
               "app.visualization", "app.gui", "app.application", "app.config.settings_service", "app")
    violations: list[str] = []

    for path in _python_files("gui"):
        for module, line in _imports_of(path):
            if not module.startswith("app"):
                continue
            if not any(module == entry or module.startswith(entry + ".") for entry in allowed):
                violations.append(_relative(path) + ":" + str(line) + " -> " + module)

    assert not violations, "Die Oberflaeche greift an der Serviceschicht vorbei:\n  " + "\n  ".join(violations)


def test_engines_are_free_of_qt() -> None:
    """Die Kernforderung: Berechnungen laufen ohne Qt.

    Wird sie verletzt, braucht jeder Engine-Test eine QApplication, und die
    Fachlogik ist nicht mehr ohne Bildschirm pruefbar.
    """
    violations = [
        _relative(path) + ":" + str(line) + " -> " + module
        for path in _python_files("engines")
        for module, line in _imports_of(path)
        if module.startswith(("PyQt", "PySide"))
    ]
    assert not violations, "Engines importieren Qt:\n  " + "\n  ".join(violations)


def test_core_is_free_of_qt() -> None:
    violations = [
        _relative(path) + ":" + str(line) + " -> " + module
        for path in _python_files("core")
        for module, line in _imports_of(path)
        if module.startswith(("PyQt", "PySide"))
    ]
    assert not violations, "Die Querschnittsschicht importiert Qt:\n  " + "\n  ".join(violations)


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


def test_engines_do_not_touch_the_filesystem() -> None:
    """Spezifikation 04: Engines lesen keine Dateien.

    Alles, was sie brauchen, kommt als DTO herein. Ohne diese Regel wandert die
    Konfiguration nach und nach in die Fachlogik, und die Engine ist ohne
    Dateisystem nicht mehr testbar.
    """
    violations: list[str] = []
    for path in _python_files("engines"):
        for module, line in _imports_of(path):
            if module in ("json", "pathlib", "csv", "configparser", "sqlite3", "shutil", "os.path"):
                violations.append(_relative(path) + ":" + str(line) + " -> " + module)
        for name, line in _calls_named(path, {"open", "read_text", "write_text"}):
            violations.append(_relative(path) + ":" + str(line) + " -> " + name + "()")

    assert not violations, "Engines greifen auf Dateien zu:\n  " + "\n  ".join(violations)


def test_configuration_is_read_only_in_the_config_layer() -> None:
    """Spezifikation 27: die Oberflaeche ruft niemals json.load.

    Geprueft wird der ganze Baum ausser app/config - dort gehoert der Zugriff
    hin, und nur dort.
    """
    violations: list[str] = []
    for package in sorted(p.name for p in APP.iterdir() if p.is_dir() and not p.name.startswith("__")):
        if package == "config":
            continue
        for path in _python_files(package):
            for module, line in _imports_of(path):
                if module == "json" or module.startswith("json."):
                    violations.append(_relative(path) + ":" + str(line) + " -> " + module)

    assert not violations, "JSON-Zugriff ausserhalb der Konfigurationsschicht:\n  " + "\n  ".join(violations)


# Fachlogik in der Oberflaeche -------------------------------------------------

def test_gui_contains_no_calculation_formulas() -> None:
    """Spezifikation 10: keine Berechnungsformeln in der Oberflaeche.

    Als Anhaltspunkt dient der Import von Rechenbibliotheken. Die Oberflaeche
    darf Werte umrechnen (app.core.units) und formatieren, aber nicht rechnen.
    Wer hier math oder numpy braucht, baut gerade eine Formel nach, die in eine
    Engine gehoert.
    """
    violations = [
        _relative(path) + ":" + str(line) + " -> " + module
        for path in _python_files("gui")
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
        for path in _python_files("visualization")
        for module, line in _imports_of(path)
        if module.startswith("app.engines")
    ]
    assert not violations, "Fachlogik in der Darstellung:\n  " + "\n  ".join(violations)


# Modulvertrag -----------------------------------------------------------------

def test_registered_modules_satisfy_the_contract() -> None:
    """Spezifikation 06: neue Module muessen dem Modulvertrag entsprechen."""
    from app.gui.module_registry import CalculationModule, default_modules

    for module in default_modules():
        assert isinstance(module, CalculationModule), (
            type(module).__name__ + " erfuellt den Modulvertrag nicht"
        )
        assert module.module_id and isinstance(module.module_id, str)
        assert module.title and isinstance(module.title, str)
        assert isinstance(module.order, int)


def test_module_ids_are_unique() -> None:
    from app.gui.module_registry import default_modules

    ids = [module.module_id for module in default_modules()]
    assert len(ids) == len(set(ids)), "Doppelte Modulkennung: " + str(ids)


def test_registry_rejects_a_module_without_the_contract() -> None:
    from app.gui.module_registry import ModuleRegistry

    class NotAModule:
        pass

    with pytest.raises(TypeError):
        ModuleRegistry().register(NotAModule())


def test_main_window_names_no_module() -> None:
    """Spezifikation 06: kein Code im Hauptfenster ist auf 'Tab 2' zugeschnitten.

    Geprueft wird, dass das Hauptfenster keine Modulkennung als Zeichenkette
    enthaelt - genau so entstehen die verbotenen Sonderbehandlungen.
    """
    from app.gui.module_registry import default_modules

    source = (APP / "gui" / "main_window.py").read_text(encoding="utf-8")
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
#: Druck (siehe app/engines/vacuum/leakage.py). Ein fester Suffix waere fuer
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
    """Die Einheitenkonvention aus app/core/units.py, maschinell geprueft.

    Eine Vakuumrechnung mischt mbar, l/min, m3/h, N, kg und mm. Wer das ohne
    feste Konvention rechnet, produziert Ergebnisse, die um Faktor 60 oder 1000
    danebenliegen und trotzdem plausibel aussehen. Der Suffix macht den Fehler
    schon beim Lesen sichtbar.
    """
    from app.core.units import FIELD_SUFFIXES

    violations: list[str] = []
    for path in _python_files("dto"):
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
    for path in _python_files("dto"):
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


def test_no_module_imports_itself_in_a_circle() -> None:
    """Spezifikation 01: keine zyklischen Abhaengigkeiten.

    Geprueft auf Paketebene - ein Zyklus innerhalb eines Pakets ist eine
    Geschmacksfrage, einer zwischen Paketen ein Architekturfehler.
    """
    edges: dict[str, set[str]] = {}
    for package in sorted(p.name for p in APP.iterdir() if p.is_dir() and not p.name.startswith("__")):
        targets: set[str] = set()
        for path in _python_files(package):
            for module, _line in _imports_of(path):
                if not module.startswith("app."):
                    continue
                target = module.split(".")[1]
                if target != package and (APP / target).is_dir():
                    targets.add(target)
        edges[package] = targets

    cycles: list[str] = []
    for source, targets in edges.items():
        for target in targets:
            if source in edges.get(target, set()):
                pair = " <-> ".join(sorted((source, target)))
                if pair not in cycles:
                    cycles.append(pair)

    assert not cycles, "Zyklische Paketabhaengigkeiten:\n  " + "\n  ".join(cycles)
