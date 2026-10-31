"""Die Oberflaeche: wie DIESES Programm aussieht und sich bedienen laesst.

Zwei Sorten Inhalt, und die Trennung ist der Sinn dieses Pakets.

GEGENSTANDSFREI, direkt hier:

    theme.py          Farben, Schriftgroesse, Stylesheet - hell und dunkel
    notifications.py  wie Meldungen den Benutzer erreichen
    help_dialog.py    das Hilfefenster und der Lader fuer seine Kapitel
    form_builder.py   Formulare aus Beschreibungen statt aus Quelltext
    window_state.py   gemerkte Fenstergroessen und Teilerstellungen
    debounce.py       sammelt schnelle Eingaben zu einem Rechenlauf

JE SCHEIBE, in einem Unterordner:

    pallet/   tab.py . form.py . renderer.py . scene_3d.py
    vacuum/   tab.py . renderer.py

Die Unterordner duerfen ihre Scheibe kennen, der gegenstandsfreie Teil darf
es nicht - und keiner der beiden darf den anderen Unterordner kennen. Drei
Eintraege in FORBIDDEN, eine Regel je Zeile.

Die Bedienelemente selbst stehen NICHT hier, sondern in qt_controls_pyrs:
compact.py (die dichter gesetzten Fassungen), formbuilder.py (Formulare als
Beschreibung), windowstate.py und debouncer.py. Sie waren fachfrei, und
mehrere Programme an dieser Bibliothek sollen gleich aussehen - dieselbe
Oberflaeche zweimal zu pflegen ist der sichere Weg, dass sie es nicht mehr
tun. Was hier bleibt, ist das, was nur TRXing betrifft.

Kein Modul DIREKT in diesem Ordner darf app.pallet, app.vacuum oder
app.domain importieren, und auch nicht pallet/ oder vacuum/ daneben. Das ist
die scharfste Regel im Programm und die nuetzlichste: sie ist der Grund,
warum sich der Inhalt ueberhaupt in eine Bibliothek heben liess. Ein einziger
Import aus app.domain - und sei es nur fuer eine Typangabe - macht aus einem
Bedienelement ein TRXing-Bedienelement.

Fuer pallet/ und vacuum/ gilt sie NICHT, und das muss so sein: ein Tab lebt
davon, seine Scheibe zu kennen. Dass die Regel beim Umzug der Tabs am
2026-11-01 nicht einfach verwaessert wurde, haengt an einer Zeile in
_python_files() - jede Datei faellt unter die GENAUESTE Regel, nicht unter
die naechstbeste.

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
