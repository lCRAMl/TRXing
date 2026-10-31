"""Die Oberflaeche: wie das Programm aussieht und sich bedienen laesst.

Hier liegt alles, was Qt anfasst, ohne vom Fach etwas zu wissen - Farben,
Bedienelemente, Formularbau, Meldungen, Hilfe. Kein Modul dieses Pakets darf
app.palette oder app.vakuum importieren: der Werkzeugkasten kennt keinen
Gegenstand. Umgekehrt holen sich beide Scheiben hier ihre Bauteile.

Die Datenordner liegen mit: darkstyle/ (Fremddatei, unangetastet) und icons/.
Sie muessen neben darstellung.py bleiben, weil darkstyle_dir() den Ordner
ueber __file__ neben sich sucht.
"""
