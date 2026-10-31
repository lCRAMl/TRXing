"""Die Technik: was das Programm am Laufen haelt.

Hintergrundarbeit, Abbruch, Fortschritt, Fehlerprotokoll, Verzeichnisse.
Nichts hiervon weiss, WAS gerechnet wird - und das ist der Sinn der Trennung:
dieselbe Mechanik traegt jede neue Scheibe, ohne etwas von ihr zu lernen.

Dies ist die unterste Lage. Sie importiert nichts aus app.fach, nichts aus
app.oberflaeche und nichts aus den Scheiben; alle anderen importieren von
hier. Die Richtung ist einseitig und soll es bleiben - sobald ein Modul hier
nach oben greift, ist die Lage keine Lage mehr.
"""
