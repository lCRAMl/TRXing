"""Die Oberflaeche: wie DIESES Programm aussieht und sich bedienen laesst.

Drei Module, und das ist Absicht:

    theme.py   Farben, Schriftgroesse, Stylesheet - hell und dunkel
    notifications.py     wie Meldungen den Benutzer erreichen
    help_dialog.py         das Hilfefenster und der Lader fuer seine Kapitel

Die Bedienelemente selbst stehen NICHT hier, sondern in qt_controls_pyrs:
compact.py (die dichter gesetzten Fassungen), formbuilder.py (Formulare als
Beschreibung), windowstate.py und debouncer.py. Sie waren fachfrei, und
mehrere Programme an dieser Bibliothek sollen gleich aussehen - dieselbe
Oberflaeche zweimal zu pflegen ist der sichere Weg, dass sie es nicht mehr
tun. Was hier bleibt, ist das, was nur TRXing betrifft.

Kein Modul dieses Pakets darf app.pallet, app.vacuum oder app.domain
importieren. Das ist die scharfste Regel im Programm und die nuetzlichste: sie
ist der Grund, warum sich der Inhalt ueberhaupt in eine Bibliothek heben
liess. Ein einziger Import aus app.domain - und sei es nur fuer eine Typangabe -
macht aus einem Bedienelement ein TRXing-Bedienelement.

Drei Datenordner liegen mit, und alle drei muessen NEBEN ihrem Modul bleiben:
sie werden ueber __file__ gefunden, damit sie im Quelltextbaum und im
entpackten Paket am selben relativen Pfad stehen.

    darkstyle/    Fremddatei, unangetastet - gepflegt mit dem Projekt
                  Qt-Frameless-Window-DarkStyle. Gesucht von darkstyle_dir().
    icons/        das Programmsymbol, zweifach gebraucht: als Symbol der .exe
                  und zur Laufzeit als Fenstersymbol.
    help_texts/   die sieben Kapitel der Hilfe, eine Datei je Kapitel.
                  Gesucht von help_texts_dir().

Jeder von ihnen braucht einen --add-data-Eintrag in AUTOBUILD.py. Fehlt einer,
merkt man es nicht beim Bauen, sondern beim Benutzen der fertigen Datei - fuer
zwei von ihnen gibt es deshalb einen Test.
"""
