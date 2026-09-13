"""Einstiegspunkt: python -m app

Mit --check laeuft nur die Startsequenz und gibt den Systemzustand aus, ohne
Oberflaeche. Das ist der schnellste Weg, eine kaputte Konfiguration oder ein
unvollstaendiges Paket zu erkennen - und der einzige, der ohne Bildschirm
funktioniert.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app import APP_NAME, APP_SLUG, __version__
from app.application import Application


def _print_report(report: dict, duration: float, notes: list[str]) -> None:
    print(APP_NAME + " " + __version__)
    print("  Start        : " + format(duration, ".3f") + " s")
    print("  Konfiguration: " + str(report.get("config_dir", "?")))
    print("  Bestand      : " + str(report.get("pallets", 0)) + " Paletten, "
          + str(report.get("patterns", 0)) + " Muster, "
          + str(report.get("suction_cups", 0)) + " Sauger"
          + ("" if report.get("config_ok") else "   (mit Beanstandungen)"))
    print("  Module       : " + ", ".join(report.get("modules", [])))
    print("  Pools        : " + str(report.get("pools", {})))
    print("  Protokoll    : " + str(report.get("log_file", "?")))
    print("  Probleme     : " + str(report.get("problems", 0)))
    for note in notes:
        print("  Hinweis      : " + note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app", description=APP_NAME)
    parser.add_argument("--version", action="version", version=APP_NAME + " " + __version__)
    parser.add_argument("--config", metavar="PFAD", default=None,
                        help="Alternatives Konfigurationsverzeichnis")
    parser.add_argument("--check", action="store_true",
                        help="Nur Startsequenz pruefen, keine Oberflaeche")
    parser.add_argument("--json", action="store_true", help="Statusbericht als JSON")
    args = parser.parse_args(argv)

    application = Application(config_directory=Path(args.config) if args.config else None)
    result = application.startup()

    if not result.ok:
        print("Start fehlgeschlagen: " + result.message, file=sys.stderr)
        application.shutdown()
        return 2

    if args.check or args.json:
        report = application.status_report()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        else:
            _print_report(report, result.duration_s, result.notes)
        application.shutdown()
        return 0 if report.get("config_ok") else 1

    return _run_gui(application)


def _claim_taskbar_identity() -> None:
    """Meldet Windows eine eigene Anwendungskennung.

    Ohne sie haelt Windows den Quelltextbetrieb fuer "python.exe": das Fenster
    traegt zwar das gesetzte Symbol, die Taskleiste aber zeigt das Symbol von
    Python und gruppiert die Anwendung mit jedem anderen Python-Fenster. Die
    Kennung trennt beides.

    Die gepackte Fassung braucht das nicht - sie ist eine eigene .exe mit
    eigenem Symbol. Der Aufruf schadet dort aber auch nicht, und eine Fallunter-
    scheidung waere mehr Aufwand als der Aufruf selbst. Auf einem System ohne
    diese Windows-Funktion passiert nichts.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_SLUG + "." + APP_NAME
        )
    except (AttributeError, OSError):
        pass


def _run_gui(application: Application) -> int:
    """Startet die Oberflaeche.

    Ein Fehler hier ist der eine Fall, in dem ein modaler Dialog richtig ist
    (Spezifikation 09): ohne Fenster gibt es keine Statusleiste, die die
    Meldung aufnehmen koennte.
    """
    from PyQt6.QtWidgets import QApplication, QMessageBox

    _claim_taskbar_identity()

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationVersion(__version__)

    # Einmal fuer die ganze Anwendung: jedes Fenster und jeder Dialog erbt es.
    from app.gui.icons import app_icon

    qt_app.setWindowIcon(app_icon())

    # Vor dem ersten Fenster: eine spaeter gesetzte Palette erreicht bereits
    # erzeugte Widgets nur teilweise. Steht Windows auf helle Fenster, aendert
    # der Aufruf nichts.
    from app.gui.theme import apply_theme

    if apply_theme(qt_app):
        logging.getLogger("app").info("Dunkle Fassung: Windows steht auf dunkle Fenster")

    try:
        from app.gui.main_window import MainWindow

        window = MainWindow(application.context, application.registry)
    except Exception as exc:
        application.reporter.exception(exc, source="startup")
        QMessageBox.critical(
            None, APP_NAME + " - Start fehlgeschlagen",
            "Das Hauptfenster konnte nicht aufgebaut werden.\n\n"
            + type(exc).__name__ + ": " + str(exc)
            + "\n\nEinzelheiten stehen im Protokoll:\n" + str(application.log_file),
        )
        application.shutdown()
        return 3

    window.show()
    try:
        return qt_app.exec()
    finally:
        application.shutdown()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
