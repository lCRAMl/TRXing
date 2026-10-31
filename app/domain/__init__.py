"""Das Fach: der Gegenstand, um den es geht.

Das Paket, die Einheiten, die Geometrie, die Legemuster, der Katalog der
wirklichen Paletten und Sauger, der gemeinsame Zustand. Alles, was beide
Scheiben brauchen und was keine von beiden allein besitzt.

Qt-frei. Das ist keine Reinheitsregel, sondern der Grund, warum der Grossteil
der Testsuite in Sekunden statt Minuten laeuft: diese Tests brauchen keine
QApplication. Ein einziger Qt-Import hier kippt das, ohne dass sofort etwas
auffaellt - deshalb steht die Liste in tests/test_architecture.py.

Dateien liest genau ein Modul: catalog.py, und zwar nur lesend. Alles uebrige
bekommt gereicht, was es braucht.

Zwei Dinge, die hier ueberraschen und beide einen Grund haben:

layer_patterns.py klingt nach Palettierung, steht aber hier - app/vacuum/
layout.py legt mit denselben Mustern die Pakete unter der Platte aus.

catalog.py importiert app.pallet.models und app.vacuum.models, obwohl es unter
ihnen liegt: es liest die JSON-Kataloge in genau diese Datenobjekte ein. Das
ist der einzige Ring im Programm und als Ausnahme in
tests/test_architecture.py eingetragen - samt dem, was ihn aufloesen wuerde.
"""
