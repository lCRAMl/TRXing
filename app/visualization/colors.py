"""Farbabstufungen der Zeichnungen.

Eine blasse Fuellung soll ihre Bedeutung behalten, gleich ob die Anwendung hell
oder dunkel laeuft. "Blass" heisst dabei nicht "heller", sondern "naeher am
Hintergrund": auf weissem Grund wird aufgehellt, auf dunklem abgedunkelt. Mit
einem festen lighter() waere die dunkle Fassung voller greller Flecken, und der
Ring, der die Aussage traegt, ginge daneben unter.

Die Richtung steckt in der Palette (Palette.dark) und damit an derselben
Stelle wie die Farben selbst - die Renderer fragen nicht, welches Farbschema
gilt.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor

from app.visualization.theme import PALETTE


def toned(color: QColor | str, amount: int = 170) -> QColor:
    """Blassere Fassung einer Farbe, in Richtung des Hintergrunds.

    amount ist der Faktor von QColor.lighter()/darker() in Prozent: 100 laesst
    die Farbe unveraendert, 180 rueckt sie deutlich an den Hintergrund heran.
    """
    base = color if isinstance(color, QColor) else QColor(color)
    return base.darker(amount) if PALETTE.dark else base.lighter(amount)
