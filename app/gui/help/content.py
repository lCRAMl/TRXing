"""Der Inhalt der Rechenwegdokumentation.

Getrennt vom Dialog, weil es Text ist und kein Bedienelement: so laesst er sich
ohne Qt pruefen, und ein spaeterer Export nach HTML oder PDF braucht den Dialog
nicht.

Anspruch: wer diese Seiten liest, kann jedes angezeigte Ergebnis von Hand
nachrechnen und findet im Quelltext die Stelle, an der es entsteht. Deshalb
steht bei jedem Abschnitt die Datei dabei, in der die Formel tatsaechlich
implementiert ist - eine Dokumentation, die man nicht gegen den Code halten
kann, veraltet unbemerkt.

Die Formeln stehen als Text, nicht als Bild: sie bleiben damit durchsuchbar,
kopierbar und in jeder Schriftgroesse lesbar.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.gui.theme import PALETTE


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


# 1 Grundlagen ------------------------------------------------------------------

_BASICS = """
<h1>Grundlagen</h1>
<p>Diese Seiten beschreiben jede Rechnung, die die Anwendung ausfuehrt &ndash;
mathematisch und mit Verweis auf die Stelle im Quelltext. Wer sie liest, kann
jedes angezeigte Ergebnis von Hand nachpruefen.</p>

<h2>Einheiten</h2>
<p>Intern rechnet die Anwendung durchgaengig in diesen Einheiten. Jedes
Datenfeld traegt sie im Namen; ein Feld ohne Einheitensuffix faellt beim
Testlauf durch.</p>
<table>
<tr><th>Groesse</th><th>Einheit</th><th>Feldsuffix</th></tr>
<tr><td>Laenge</td><td>Millimeter</td><td>_mm</td></tr>
<tr><td>Flaeche</td><td>Quadratmillimeter</td><td>_mm2</td></tr>
<tr><td>Masse</td><td>Kilogramm</td><td>_kg</td></tr>
<tr><td>Kraft</td><td>Newton</td><td>_n</td></tr>
<tr><td>Druck</td><td>Pascal</td><td>_pa</td></tr>
<tr><td>Volumenstrom</td><td>Kubikmeter je Sekunde</td><td>_m3s</td></tr>
<tr><td>Beschleunigung</td><td>Meter je Sekundenquadrat</td><td>_ms2</td></tr>
</table>

<h3>Vorzeichen des Unterdrucks</h3>
<p>Unterdruck wird immer als <b>positive Druckdifferenz</b> zur Umgebung
gefuehrt. Die im Datenblatt uebliche Schreibweise &minus;0,6&nbsp;bar sind hier
60000&nbsp;Pa. Ein negatives Vorzeichen im Rechenweg waere eine dauerhafte
Fehlerquelle; umgerechnet wird erst in der Anzeige.</p>
""" + _formula(
    "dp  =  p_Umgebung - p_innen",
    "",
    "-0,6 bar  =  600 mbar  =  60000 Pa",
) + _source("app/core/units.py", "alle Umrechnungen, Naturkonstanten, Suffixliste") + """

<h2>Umrechnungen</h2>
""" + _formula(
    "1 mbar      = 100 Pa",
    "1 bar       = 100000 Pa",
    "1 l/min     = 1/60000 m3/s   = 1,6667e-5 m3/s",
    "1 m3/h      = 1/3600 m3/s    = 2,7778e-4 m3/s",
    "1 mm2       = 1e-6 m2",
) + """

<h2>Verwendete Konstanten</h2>
<table>
<tr><th>Groesse</th><th>Wert</th><th>Verwendung</th></tr>
<tr><td>Erdbeschleunigung g</td><td>9,80665 m/s2</td><td>Kraftbilanz</td></tr>
<tr><td>Umgebungsdruck</td><td>101325 Pa</td><td>Blendenstroemung, einstellbar</td></tr>
<tr><td>Luftdichte</td><td>1,204 kg/m3</td><td>Massen- in Volumenstrom</td></tr>
<tr><td>Gaskonstante Luft R</td><td>287,058 J/(kg&middot;K)</td><td>Blendenstroemung</td></tr>
<tr><td>Isentropenexponent kappa</td><td>1,4</td><td>Blendenstroemung</td></tr>
<tr><td>Bezugstemperatur</td><td>293,15 K</td><td>Blendenstroemung</td></tr>
</table>
"""


# 2 Paketdaten ------------------------------------------------------------------

_PACKAGE = """
<h1>Paketdaten</h1>
<p>Der einfachste Rechenweg der Anwendung, aber der folgenreichste: alle
uebrigen Ergebnisse haengen an diesen vier Zahlen.</p>

<h2>Abgeleitete Werte</h2>
""" + _formula(
    "Volumen          V   = L * B * H                 [mm3]",
    "                     = L * B * H / 1e6           [Liter]",
    "",
    "Grundflaeche     A   = L * B                     [mm2]",
    "",
    "Dichte           rho = m / (V / 1e9)             [kg/m3]",
) + """
<p>Beispiel 400 &times; 300 &times; 200&nbsp;mm bei 5&nbsp;kg:</p>
""" + _formula(
    "V   = 400 * 300 * 200      = 24 000 000 mm3 = 24,00 Liter",
    "A   = 400 * 300            = 120 000 mm2   = 1200 cm2",
    "rho = 5 / 0,024            = 208,3 kg/m3",
) + _source("app/dto/package.py", "PackageSpec.volume_mm3, .density_kgm3, .footprint_area_mm2") + """

<h2>Stapelhoehe aus der zulaessigen Stapellast</h2>
<p>Das unterste Paket eines Saeulenstapels traegt alle darueber. Bei n Paketen
uebereinander sind das (n&minus;1) Stueck:</p>
""" + _formula(
    "Auflast unten    F = (n - 1) * m",
    "",
    "zulaessig:       (n - 1) * m  <=  F_max",
    "",
    "                 n  =  floor(F_max / m) + 1",
) + """
<p>Beispiel: 5&nbsp;kg je Paket, 15&nbsp;kg zulaessige Stapellast &rarr;
<code>floor(15 / 5) + 1 = 4</code> Pakete uebereinander. Das unterste traegt
dann genau 15&nbsp;kg &ndash; erlaubt, weil die angegebene Stapellast die
zulaessige Hoechstlast ist.</p>
<div class="note">Diese Formel ist nur eine <b>erste Schranke</b>. Sie gilt
exakt fuer den Saeulenstapel. Sobald ein Verband im Spiel ist, verteilt sich
die Last anders &ndash; die genaue Rechnung steht unter
<i>Palettierung &rarr; Lastkaskade</i>.</div>
""" + _source("app/engines/palletizing/loads.py", "max_layers_by_stack_load()") + """

<h2>Validierung</h2>
<p>Geprueft wird feldweise, damit die Meldung am richtigen Eingabefeld
erscheint:</p>
<ul>
<li>Wert ist eine endliche Zahl (kein NaN, kein Unendlich)</li>
<li>Laenge, Breite, Hoehe: groesser 0 und hoechstens 5000&nbsp;mm</li>
<li>Gewicht: groesser 0 und hoechstens 2000&nbsp;kg</li>
<li>Stapellast: nicht negativ, hoechstens 20000&nbsp;kg</li>
</ul>
<p>Die Obergrenzen fangen die haeufigste Verwechslung ab: eine Laenge von
400000 ist eine Eingabe in Mikrometern oder ein vergessenes Komma, keine
Palette.</p>
""" + _source("app/dto/package.py", "validate_package()")


# 3 Palettierung ----------------------------------------------------------------

_PALLET = """
<h1>Tab 1 &ndash; Palettierung</h1>

<h2>Nutzbare Palettenflaeche</h2>
<p>Ueberstand erweitert die Ladeflaeche, Randabstand verkleinert sie. Beide
wirken je Seite, also doppelt:</p>
""" + _formula(
    "L_nutz = L_Palette + 2 * (Ueberstand - Randabstand)",
    "B_nutz = B_Palette + 2 * (Ueberstand - Randabstand)",
) + _source("app/dto/pallet.py", "PalletSpec.usable_length_mm / .usable_width_mm") + """

<h2>Aufbau einer Lage</h2>
<p>Alle Muster fuellen ein Rechteck mit gleichen Rechtecken. Das Rechteck ist
bei der Palettierung die Palettenflaeche, beim Vakuumtab die Plattenflaeche
&ndash; dieselbe Rechenschicht, deshalb ist ein Muster dort wiederverwendbar.</p>

<h3>Rastermass mit Spalt</h3>
""" + _formula(
    "Rastermass       t_x = l + s        (s = Spalt zwischen Paketen)",
    "                 t_y = b + s",
    "",
    "Spalten          n_x = floor((L_nutz + s) / t_x)",
    "Reihen           n_y = floor((B_nutz + s) / t_y)",
    "",
    "Stueck je Lage   n   = n_x * n_y",
) + """
<p>Das <code>+ s</code> im Zaehler ist kein Rundungstrick: der letzte Nachbar
in einer Reihe braucht rechts von sich keinen Spalt mehr.</p>

<h3>Beide Ausrichtungen</h3>
<p>Jedes Muster rechnet das Raster zweimal &ndash; einmal mit dem Paket laengs,
einmal quer &ndash; und nimmt das dichtere Ergebnis. Bei 400 &times; 300&nbsp;mm
auf 1200 &times; 800&nbsp;mm:</p>
""" + _formula(
    "laengs:  floor(1200/400) * floor(800/300) = 3 * 2 = 6",
    "quer:    floor(1200/300) * floor(800/400) = 4 * 2 = 8   <-- gewaehlt",
) + """

<h3>Guillotine-Verfahren</h3>
<p>Hauptraster in einer Ausrichtung, danach die beiden Reststreifen rechts und
oben mit der um 90 Grad gedrehten Ausrichtung nachfuellen:</p>
""" + _formula(
    "Rest rechts   L_rest = L_nutz + s - n_x * t_x",
    "Rest oben     B_rest = B_nutz + s - n_y * t_y",
    "",
    "in beiden Streifen erneut ein Raster, Kanten vertauscht",
) + """

<h3>Laeuferverband</h3>
<p>Jede zweite Reihe um eine halbe Paketlaenge versetzt. Gesetzt werden nur
vollstaendige Pakete &ndash; am versetzten Reihenende bleibt eine halbe
Paketlaenge frei. Genau das macht den Verband aus: die Stoesse der Reihen liegen
nicht uebereinander.</p>
""" + _formula(
    "Versatz Reihe r    v = (r ungerade) ? t_x / 2 : 0",
    "Position           x = v + k * t_x     solange  x + l <= L_nutz",
) + """

<h3>Wechselnde Ausrichtung: warum bandweise</h3>
<p>Schachbrett, Windrad, Spirale und Randverband mischen zwei Ausrichtungen
innerhalb einer Lage. Feldweise &ndash; also von Paket zu Paket &ndash; geht
das nur bei quadratischer Grundflaeche ohne Luecke auf:</p>
""" + _formula(
    "Paket 400 x 300 mm",
    "",
    "  laengs:  Hoehe im Band = 300 mm",
    "  quer:    Hoehe im Band = 400 mm",
    "",
    "  nebeneinander im selben Band  ->  100 mm bleiben zwangslaeufig frei",
) + """
<div class="warn">Eine Luecke mitten in der Ladung ist kein Schoenheitsfehler:
die Pakete verrutschen darin beim Transport. Bei rechteckigen Paketen wechselt
die Ausrichtung deshalb <b>bandweise</b> &ndash; jedes Band besteht aus vollen
Reihen einer Ausrichtung, die Baender liegen unmittelbar aufeinander. Frei
bleibt allenfalls ein Streifen am Aussenrand, und der ist bei keiner
Paketgroesse zu vermeiden.</div>
<p>Bei quadratischen Paketen bleibt der feldweise Wechsel erhalten &ndash; dort
geht er exakt auf. Welche Wechselfolge ein Muster verwendet:</p>
<table>
<tr><th>Muster</th><th>Band k gedreht, wenn</th></tr>
<tr><td>Schachbrett</td><td>k ungerade</td></tr>
<tr><td>Windrad</td><td>(k div 2) ungerade &ndash; je zwei Baender gemeinsam</td></tr>
<tr><td>Spiralverband</td><td>min(k, n&minus;1&minus;k) ungerade &ndash; von aussen nach innen</td></tr>
<tr><td>Randverband</td><td>k weder erstes noch letztes Band &ndash; Kern gedreht</td></tr>
</table>
<p>Der Ringstapel ist die Ausnahme: sein freier Kern ist die Definition des
Musters, nicht ein Mangel.</p>
""" + _source("app/engines/patterns/strategies.py",
              "alle Muster; alternating_bands() in base.py") + """

<h2>Stapelaufbau</h2>
<p>Die Grundlage wird nach oben wiederholt. Drei Modi:</p>
<table>
<tr><th>Modus</th><th>Lage k</th><th>Verwendung</th></tr>
<tr><td>identical</td><td>immer die Grundlage</td><td>Saeulen-, Blockstapel</td></tr>
<tr><td>mirror</td><td>ungerade Lagen um 180 Grad um die eigene Mitte gedreht</td><td>Verband</td></tr>
<tr><td>rotate90</td><td>ungerade Lagen aus einer um 90 Grad gedrehten Lage</td><td>Kreuzverband</td></tr>
</table>
<p>Gespiegelt wird um die <b>eigene</b> Mitte der Lage, nicht um den
Palettenursprung &ndash; sonst wanderte jede zweite Lage an den
gegenueberliegenden Rand und der Stapel bekaeme eine Schraeglage:</p>
""" + _formula(
    "x' = x_min + x_max - x - l",
    "y' = y_min + y_max - y - b",
) + _source("app/engines/palletizing/stacking.py", "repeat(), mirror_footprints()") + """

<h2>Lagenzahl</h2>
<p>Drei Grenzen, die kleinste gewinnt:</p>
""" + _formula(
    "aus der Hoehe        n_H = floor(H_max / h)",
    "aus der Palettenlast n_G = floor(G_max / (n_Lage * m))",
    "aus der Stapellast   n_S = floor(F_max / m) + 1",
    "",
    "                     n   = min(n_H, n_G, n_S)",
) + """
<p>Welche Grenze gegriffen hat, steht im Ergebnis unter
<i>Begrenzt durch</i>. Anschliessend wird die tatsaechliche Lastkaskade
gerechnet und der Stapel gekuerzt, falls dabei ein Paket ueberlastet wird
&ndash; n_S ist nur eine Schranke, keine Garantie.</p>

<h2>Lastkaskade</h2>
<p>Die einfache Regel &bdquo;so viele Pakete darueber&ldquo; stimmt exakt fuer
den Saeulenstapel. Im Verband liegt ein Paket auf mehreren Nachbarn auf und gibt
seine Last anteilig weiter &ndash; das ist der eigentliche Zweck eines
Verbands.</p>
<p>Gerechnet wird von oben nach unten. Jedes Paket q gibt sein Eigengewicht plus
alles, was es bereits traegt, an die Pakete p darunter weiter, im Verhaeltnis
der Ueberdeckung der Standflaechen:</p>
""" + _formula(
    "Abgabe von q       F_q = m_q + getragen(q)",
    "",
    "Ueberdeckung       A_pq = Flaeche(Standflaeche p geschnitten mit q)",
    "",
    "getragen(p)  +=   F_q * A_pq / Summe(A_iq ueber alle i darunter)",
) + """
<p>Liegt unter einem Paket gar nichts (Muster mit freiem Kern), geht seine Last
direkt auf die Palette.</p>
<h3>Bewertung</h3>
""" + _formula(
    "Auslastung     p = getragen / F_max * 100 %",
    "",
    "     p <= 80 %      in Ordnung",
    "80 < p <= 100 %     grenzwertig",
    "     p >  100 %     ueberlastet",
) + """
<p>Genau 100&nbsp;% zaehlt als grenzwertig, nicht als ueberlastet: die
angegebene Stapellast ist die zulaessige Hoechstlast, ihr Erreichen also
erlaubt.</p>
<div class="note"><b>Grenzen des Modells:</b> Brueckenbildung und Steifigkeit
der Kartons bleiben unberuecksichtigt. Eine Kiste, die zwischen zwei Nachbarn
spannt, traegt in Wirklichkeit anders. Das exakt zu rechnen erforderte eine
Strukturanalyse; verwendet wird die uebliche statische Naeherung.</div>
""" + _source("app/engines/palletizing/loads.py", "analyze()") + """

<h2>Ausnutzung</h2>
""" + _formula(
    "Flaeche    eta_A = (n_Lage * l * b) / (L_nutz * B_nutz)",
    "",
    "Raum       eta_V = (n_gesamt * l * b * h) / (L_nutz * B_nutz * H_Stapel)",
    "",
    "Gesamthoehe      H = n_Lagen * h  +  Bauhoehe der Palette",
    "Gesamtgewicht    G = n_gesamt * m",
) + _source("app/engines/palletizing/optimizer.py", "_build_result()")


# 4 Vakuum: Geometrie -----------------------------------------------------------

_VACUUM_GEOMETRY = """
<h1>Tab 2 &ndash; Geometrie der Saugerplatte</h1>

<h2>Saugerraster</h2>
<p>Massgeblich fuer den Abstand ist das <b>Aussenmass unter Vakuum</b>
(Dmax(S) im Datenblatt), nicht die Nenngroesse: der Sauger weitet sich beim
Ansaugen.</p>
""" + _formula(
    "Mindestrastermass    t = Dmax(S) + Saugerabstand",
    "",
    "Randabstand          r = max(Randabstand, Dmax(S) / 2)",
    "",
    "nutzbare Spanne      s_x = L_Platte - 2r",
    "                     s_y = B_Platte - 2r",
    "",
    "Hoechstzahl          n_x = floor(s_x / t) + 1",
    "                     n_y = floor(s_y / t) + 1",
) + """
<p>Das <code>+ 1</code> ist kein Fehler: n Abstaende ergeben n+1 Positionen.</p>
<p>Der Randabstand wird nach unten auf den halben Aussendurchmesser begrenzt
&ndash; sonst haengt der aeusserste Sauger ueber die Plattenkante.</p>

<div class="note"><b>Warum die Sauger in der Zeichnung nicht aneinanderstossen.</b>
Zwischen zwei Aussenmassen liegt der eingestellte <b>Saugerabstand</b> &ndash;
das lichte Mass zwischen den Aussenkanten aus der Formel oben. Er ist der
groesste Hebel auf die Stueckzahl, groesser als die Wahl des Musters:
<table>
<tr><th>Saugerabstand</th><th>Raster, dicht an dicht</th><th>Dichteste Packung</th></tr>
<tr><td>10 mm (Vorgabe)</td><td>234</td><td>263</td></tr>
<tr><td>0 mm</td><td><b>391</b></td><td><b>428</b></td></tr>
</table>
Platte 800 &times; 600 mm, SPB2&nbsp;30. Bei 0 mm beruehren sich die
Aussenmasse; die Legende der Draufsicht schreibt das ausdruecklich dazu. Ob das
zulaessig ist, entscheidet der Aufbau &ndash; Anschlussnippel, Schlauchfuehrung
und Montagewerkzeug brauchen Platz.</div>

<h3>Saugermuster</h3>
<p>Welche Positionen daraus entstehen, entscheidet das gewaehlte Muster:</p>
<table>
<tr><th>Muster</th><th>Aufbau</th><th>Anzahl</th></tr>
<tr><td>Raster, gleichmaessig verteilt</td>
    <td>Quadratraster ueber die ganze Platte gespreizt</td><td>Bezug</td></tr>
<tr><td>Raster, dicht an dicht</td>
    <td>Quadratraster am Mindestabstand, mittig</td><td>gleich</td></tr>
<tr><td>Dichteste Packung</td>
    <td>versetzte Reihen (Dreiecksgitter)</td><td>rund +15 %</td></tr>
<tr><td>Nur am Rand</td>
    <td>aeusserer Ring des Rasters, Mitte frei</td><td>deutlich weniger</td></tr>
<tr><td>Nur ueber den Paketen</td>
    <td>dichteste Packung, auf die Kartonflaechen beschraenkt</td><td>je nach Belegung</td></tr>
</table>

<h3>Warum die dichteste Packung mehr aufnimmt</h3>
<p>Gleich grosse Kreise lassen sich im Quadratraster nur bis zu einem
Flaechenanteil von pi/4 packen, versetzt dagegen bis pi/(2&middot;sqrt(3)):</p>
""" + _formula(
    "Quadratraster    pi / 4              = 0,7854   =  78,5 %",
    "versetzt         pi / (2 * sqrt(3))  = 0,9069   =  90,7 %",
    "",
    "Verhaeltnis      0,9069 / 0,7854     = 1,155    =  +15,5 %",
) + """
<p>Im versetzten Raster faellt jeder Sauger in die Luecke zwischen zwei Saugern
der Reihe darunter. Die Reihen ruecken dadurch enger zusammen, ohne dass der
Mittenabstand zu irgendeinem Nachbarn unter das Rastermass faellt:</p>
""" + _formula(
    "Reihenabstand    t_y = t * sqrt(3)/2 = 0,866 * t",
    "Versatz          jede zweite Reihe um t/2",
    "",
    "Abstand zur Nachbarreihe:",
    "",
    "   sqrt( (t/2)^2 + (t*sqrt(3)/2)^2 )  =  t * sqrt(1/4 + 3/4)  =  t",
) + """
<div class="note">Der gesamte Block wird EINMAL zentriert, nicht jede Reihe fuer
sich. Reihenweise zu zentrieren liegt nahe, zerstoert aber genau diese
Eigenschaft: der Versatz ist dann nicht mehr ein halbes Rastermass, sondern
das, was die Zentrierung zufaellig ergibt - und der Abstand zur Nachbarreihe
faellt unter das Rastermass. Gemessen 39,7 statt 44 mm; die Sauger wuerden sich
ueberlappen.</div>

<h3>Verringerte Saugerzahl</h3>
<p>Wird weniger als die Hoechstzahl gewuenscht, wird nicht einfach weggelassen
&ndash; das ergaebe eine Platte, die unten dicht bestueckt ist und oben leer
bleibt. Sie kippte beim Anheben und griffe nur die halbe Kartonflaeche ab.</p>
<p>Stattdessen wird das Rastermass vergroessert, bis das Muster von selbst etwa
die gewuenschte Zahl liefert. Die Stueckzahl faellt monoton mit dem Rastermass,
deshalb genuegt eine Intervallhalbierung:</p>
""" + _formula(
    "gesucht:  groesstes s >= 1  mit  Anzahl(Muster, t * s)  >=  n_gewuenscht",
    "",
    "Rest, der danach noch ueber der Vorgabe liegt: von der obersten Reihe",
    "her abraeumen, abwechselnd vom rechten und linken Ende.",
) + """
<p>Die Sauger verteilen sich damit wieder ueber die ganze Platte, und die Form
des Musters bleibt erhalten &ndash; ein gespreiztes Raster bleibt ein Raster,
eine dichteste Packung bleibt versetzt.</p>
""" + _source("app/engines/vacuum/arrangements.py", "die Muster") + _source(
    "app/engines/vacuum/layout.py", "SuctionLayoutEngine.distribute(), _thin_to()"
) + """

<h3>Die Platte darf kleiner sein als das Paket</h3>
<p>Eine Saugerplatte ist regelmaessig kleiner als das, was sie hebt: sie greift
in die Mitte der Lage, und die aeusseren Kartons ragen darueber hinaus. Die
Plattengroesse begrenzt deshalb nur, wo Sauger sitzen koennen &ndash; nicht,
wie die Pakete liegen.</p>
<p>Wieviele Pakete dabei ueber die Platte hinausragen, steht in den Warnungen.
Fuer die Haltekraft zaehlt nur, was unter der Platte liegt.</p>

<h3>Aufbau von innen nach aussen</h3>
<p>Das Muster entsteht einmal auf einem festen Bereich, der von der
Plattenkante aus in GANZEN Paketen nach aussen waechst:</p>
""" + _formula(
    "Zellmass          t_x = l + s          t_y = b + s",
    "",
    "Bereich           L_ber = L_Platte + 2 * k * t_x",
    "                  B_ber = B_Platte + 2 * k * t_y",
    "",
    "k = 16, verkleinert, falls sonst mehr als 5000 Plaetze entstuenden",
) + """
<p>Zwei Eigenschaften haengen an diesem Aufbau:</p>
<ul>
<li><b>Ganze Pakete ab der Plattenkante.</b> Ein beliebig grosser Bereich
wuerde mittig zentriert, und die Plattenkante fiele mitten in eine Rasterzelle
&ndash; unter die Platte passte dann eine Reihe weniger als moeglich. Bei
600&nbsp;mm Platte und 150&nbsp;mm Paket drei statt vier.</li>
<li><b>Unabhaengig von der Stueckzahl.</b> Waechst der Bereich mit der Zahl der
Pakete, entsteht das Muster bei jeder Aenderung auf einer anderen Flaeche neu,
und die Pakete springen. Gemessen: beim Wechsel von vier auf fuenf Pakete
behielt kein einziges seine Position.</li>
</ul>
<p>Aus diesem Bereich werden die Pakete in fester Reihenfolge gewaehlt:</p>
""" + _formula(
    "1. was vollstaendig unter der Platte liegt, vor allem anderen",
    "2. innerhalb beider Gruppen: nach Abstand zur Plattenmitte,",
    "   gemessen in Rasterzellen:  d^2 = (dx / t_x)^2 + (dy / t_y)^2",
    "3. bei gleichem Abstand: die Position naeher an der Mittelreihe",
    "4. zuletzt nach Lage - unter der Platte y vor x (die Reihe wird",
    "   aufgefuellt), ausserhalb x vor y (die Spalte wird fertig)",
) + """
<p>Die Reihenfolge haengt nur von der Geometrie ab. Die Auswahl fuer n+1 ist
damit eine echte Obermenge der Auswahl fuer n &ndash; die Anordnung waechst von
innen nach aussen, statt sich neu zu wuerfeln.</p>
<p>Kriterium 1 ist nicht nur Kosmetik: unter der Platte laesst sich nur
greifen, was auch darunter liegt.</p>
<p>Kriterium 2 misst in <b>Rasterzellen</b> und nicht in Millimetern. In
Millimetern entschiede das Seitenverhaeltnis des Kartons ueber die Richtung:
bei einem Paket 200 &times; 150&nbsp;mm liegt die naechste Reihe 150&nbsp;mm
entfernt, die naechste Spalte 200&nbsp;mm &ndash; die Reihe gewaenne jedesmal,
und die Ladung waechst zu einem hohen schmalen Stapel, der oben und unten
ueberhaengt, waehrend links und rechts Plattenflaeche frei bleibt.</p>
<p>In Zellen gemessen sind beide Schritte gleich weit, und Kriterium 3
entscheidet: die Ladung waechst <b>waagerecht</b>. Auf einer Platte fuer
2&nbsp;&times;&nbsp;2 Pakete entstehen so 3&nbsp;&times;&nbsp;2 und
4&nbsp;&times;&nbsp;2 statt 2&nbsp;&times;&nbsp;3 und 2&nbsp;&times;&nbsp;4.
Waagerecht heisst dabei nicht "um jeden Preis": eine Spalte weit draussen liegt
auch in Zellen gemessen weiter weg als die naechste Reihe und kommt spaeter
&ndash; die Ladung wird breiter als hoch, aber kein Band.</p>

<h3>Zentrierung nach dem Schwerpunkt</h3>
""" + _formula(
    "x_s = Summe(x_i + l_i/2) / n            y_s = Summe(y_i + b_i/2) / n",
    "",
    "Versatz   dx = L_Platte/2 - x_s         dy = B_Platte/2 - y_s",
) + """
<p>Nach dem <b>Schwerpunkt</b>, nicht nach dem umschliessenden Rechteck. Der
Unterschied wird sichtbar, sobald die Gruppe nicht symmetrisch ist: vier gleiche
Pakete in L-Form haben ihren Schwerpunkt nicht in der Mitte ihres Rechtecks.
Nach dem Rechteck gerueckt haengt die Last seitlich am Greifer und erzeugt ein
Kippmoment &ndash; bis zu einer halben Paketlaenge Versatz.</p>
<p>Alle Pakete sind gleich schwer, der Flaechenschwerpunkt ist also zugleich der
Massenschwerpunkt. Die Verschiebung gilt fuer alle Pakete gleichermassen; die
Anordnung untereinander bleibt unberuehrt.</p>
""" + _source("app/engines/vacuum/layout.py", "package_layout(), _layout_span(), _innermost()") + """

<h2>Die drei Durchmesser eines Saugers</h2>
<p>Sie werden regelmaessig verwechselt, und die Verwechslung fuehrt zu zu knapp
ausgelegten Anlagen. Am Beispiel SPB2&nbsp;30:</p>
<table>
<tr><th>Groesse</th><th>Symbol</th><th>Wert</th><th>Bedeutung</th></tr>
<tr><td>Aussenmass unter Vakuum</td><td>Dmax(S)</td><td>34,0 mm</td><td>Platzbedarf im Raster</td></tr>
<tr><td>Auflagebereich</td><td>Ds</td><td>31,4 mm</td><td>Dichtlippe &ndash; entscheidet ueber dicht oder offen</td></tr>
<tr><td>Wirkungsbereich</td><td>d2</td><td>16,9 mm</td><td>traegt die Kraft</td></tr>
</table>
<div class="warn">Der Wirkungsbereich hat nur etwa <b>ein Viertel</b> der
Flaeche des sichtbaren Saugers. Wer die Haltekraft aus dem Aussenmass
schaetzt, rechnet sich um den Faktor vier reich. Die Draufsicht zeichnet
deshalb alle drei Kreise.</div>

<h2>Kontaktklassen</h2>
<p>Entscheidend ist der Dichtlippenring, nicht der Mittelpunkt. Nur wenn der
Ring vollstaendig auf der Kartonflaeche liegt, entsteht ein geschlossener
Raum:</p>
""" + _formula(
    "dicht (sealed):     Kreis(Ds) vollstaendig im Kartonrechteck",
    "",
    "                    x_m - Ds/2 >= x_K     und  x_m + Ds/2 <= x_K + l_K",
    "                    y_m - Ds/2 >= y_K     und  y_m + Ds/2 <= y_K + b_K",
    "",
    "teilweise:          Ueberdeckung > 0, aber nicht vollstaendig",
    "offen:              Ueberdeckung = 0",
) + """
<div class="note">Ein teilweise aufliegender Sauger <b>traegt nicht</b>. Sein
Dichtlippenring ist unterbrochen; dort stroemt Luft nach, und er verhaelt sich
wie ein offener Sauger &ndash; auch wenn er zu 95&nbsp;% aufliegt. Die eigene
Klasse bleibt trotzdem, weil sie dem Benutzer sagt, dass ein anderes Raster das
Problem loesen wuerde.</div>

<h2>Ueberdeckung Kreis gegen Rechteck</h2>
<p>Die ueberdeckte Flaeche wird <b>exakt</b> berechnet, nicht per Stichprobe
geschaetzt. Grundlage ist die Stammfunktion des Kreisrands:</p>
""" + _formula(
    "S(x)  =  0,5 * ( x * sqrt(r^2 - x^2)  +  r^2 * asin(x / r) )",
) + """
<p>Daraus die Flaeche des Kreises im Bereich links unterhalb eines Punktes
(Mittelpunkt im Ursprung, x und y positiv):</p>
""" + _formula(
    "liegt die Ecke ausserhalb des Kreises (x^2 + y^2 >= r^2):",
    "",
    "   x_y  = sqrt(r^2 - y^2)",
    "   Q    = x_y * y  +  S(x) - S(x_y)",
    "",
    "sonst (Ecke im Kreis):",
    "",
    "   Q    = x * y",
) + """
<p>Die Ueberdeckung eines beliebigen achsparallelen Rechtecks folgt daraus nach
Inklusion und Exklusion &ndash; jeder Quadrant mit eigenem Vorzeichen:</p>
""" + _formula(
    "A  =  Q(x2,y2) - Q(x1,y2) - Q(x2,y1) + Q(x1,y1)",
    "",
    "mit  x1 = x_K - x_m        x2 = x_K + l_K - x_m",
    "     y1 = y_K - y_m        y2 = y_K + b_K - y_m",
) + """
<p>Gegenprobe: ein Kreis mit r&nbsp;=&nbsp;5 zur Haelfte im Rechteck ergibt
<code>pi&middot;25/2 = 39,2699</code> &ndash; exakt, nicht genaehert.</p>
""" + _source("app/engines/geometry/shapes.py",
              "circle_rect_overlap_area_mm2(), circle_fits_in_rect()")


# 5 Vakuum: Kraft ---------------------------------------------------------------

_VACUUM_FORCE = """
<h1>Tab 2 &ndash; Kraftmodell</h1>

<h2>Die wirksame Flaeche</h2>
<p>Welche Flaeche mit der Druckdifferenz zu multiplizieren ist, entscheidet
ueber das ganze Ergebnis. Die Antwort steht implizit im Datenblatt: die
angegebene Saugkraft ist genau <code>dp &times; Kreisflaeche(d2)</code>, mit d2
dem inneren Faltendurchmesser.</p>
<table>
<tr><th>Typ</th><th>d2</th><th>aus d2 berechnet</th><th>Datenblatt</th><th>Abweichung</th></tr>
<tr><td>SPB2 20</td><td>12,0 mm</td><td>6,79 N</td><td>6,8 N</td><td>&minus;0,2 %</td></tr>
<tr><td>SPB2 25</td><td>14,5 mm</td><td>9,91 N</td><td>9,9 N</td><td>+0,1 %</td></tr>
<tr><td>SPB2 30</td><td>16,9 mm</td><td>13,46 N</td><td>14,4 N</td><td>&minus;6,5 %</td></tr>
<tr><td>SPB2 40</td><td>22,9 mm</td><td>24,71 N</td><td>24,8 N</td><td>&minus;0,4 %</td></tr>
<tr><td>SPB2 50</td><td>27,1 mm</td><td>34,61 N</td><td>34,6 N</td><td>&plusmn;0 %</td></tr>
</table>
<p>Vier von fuenf Groessen stimmen auf unter einem Prozent. Die wirksame
Flaeche ist damit keine Erfindung dieses Programms, sondern aus dem Datenblatt
abgeleitet.</p>
<p>Gerechnet wird trotzdem mit der aus der <b>Datenblattkraft</b>
zurueckgerechneten Flaeche:</p>
""" + _formula(
    "A_eff  =  F_Datenblatt / dp_Bezug * 1e6            [mm2]",
    "",
    "SPB2 30:  14,4 N / 60000 Pa * 1e6  =  240,0 mm2",
) + """
<p>Zwei Gruende: beim Bezugsdruck kommt exakt der Herstellerwert heraus, und
die einzige Groesse mit Abweichung (SPB2&nbsp;30) wird nicht stillschweigend um
6,5&nbsp;% nach unten korrigiert. Die Abweichung wird stattdessen im Rechenweg
ausgewiesen.</p>
<p>Der Bezugsdruck steht am Saugertyp, nicht als Konstante im Code &ndash;
andere Hersteller beziehen auf &minus;0,7 oder &minus;0,8&nbsp;bar.</p>
""" + _source("app/engines/vacuum/force.py", "datasheet_effective_area_mm2()") + """

<h2>Haltekraft</h2>
""" + _formula(
    "je Sauger     F = dp * A_eff / 1e6            [N]",
    "",
    "begrenzt auf  F <= Abreisskraft               (Griff von oben)",
    "              F <= Querkraft                  (seitlicher Griff)",
    "",
    "gesamt        F_ges = F * n_wirksam",
) + """
<p>Die mechanische Grenze ist keine Formalie. Bei SPB2&nbsp;30 stehen
14,4&nbsp;N Saugkraft einer Querkraft von nur 12,8&nbsp;N gegenueber &ndash;
beim seitlichen Griff begrenzt also schon bei &minus;0,6&nbsp;bar der Sauger,
nicht das Vakuum. Die Abreisskraft dagegen wird mit Vakuum allein bei den
meisten Groessen nie erreicht.</p>

<h2>Erforderliche Kraft</h2>
""" + _formula(
    "Griff von oben       F_noetig = m * (g + a) * S",
    "",
    "seitlicher Griff     F_noetig = m * (g + a) * S / mu",
) + """
<p>Die Beschleunigung a steht standardmaessig auf null; das Ergebnis ist dann
die rein statische Rechnung. Wer die Beschleunigung seines Portals oder
Roboters eintraegt, bekommt den realistischen Wert &ndash; beim Palettieren ist
der Unterschied betraechtlich.</p>
<p>Beim seitlichen Griff haengt die Last an der Reibung zwischen Sauger und
Karton; die Normalkraft muss um den Kehrwert des Reibbeiwerts groesser sein.
Der Reibbeiwert ist eine Benutzerangabe und steht in keinem Datenblatt.</p>

<h2>Rueckwaertsrechnung</h2>
<p>Die zentrale Frage des Tabs: wie schwer darf das Paket sein?</p>
""" + _formula(
    "Griff von oben        m_max = F_ges / ((g + a) * S)",
    "",
    "seitlicher Griff      m_max = F_ges * mu / ((g + a) * S)",
) + """
<p>Und die Umkehrung &ndash; welche Saugerzahl braucht ein gegebenes
Gewicht:</p>
""" + _formula(
    "n_noetig = aufrunden( F_noetig / F_je_Sauger )",
) + """
<p>Aufgerundet, denn ein halber Sauger traegt nichts.</p>
<p>Beispiel: 10&nbsp;kg, SPB2&nbsp;30 bei &minus;0,6&nbsp;bar,
Sicherheitsfaktor 1,0:</p>
""" + _formula(
    "F_noetig = 10 * 9,80665 * 1,0  = 98,07 N",
    "n        = aufrunden(98,07 / 14,4) = aufrunden(6,81) = 7 Sauger",
) + _source("app/engines/vacuum/force.py",
            "required_force_n(), max_mass_kg(), required_cup_count()") + """

<h2>Bewertung</h2>
""" + _formula(
    "Verhaeltnis   v = m_max / m_tatsaechlich",
    "",
    "   v >= 1,10     Sicher",
    "   v >= 1,00     Grenzwertig",
    "   v <  1,00     Nicht ausreichend",
) + """
<p>Die Einstufung leitet sich aus diesen Zahlen ab, nicht aus einer Heuristik
der Oberflaeche.</p>
""" + _source("app/core/result.py", "classify()")


# 6 Vakuum: Stroemung -----------------------------------------------------------

_VACUUM_FLOW = """
<h1>Tab 2 &ndash; Stroemung und Arbeitspunkt</h1>

<h2>Fremdluft eines offenen Saugers</h2>
<p>Der groesste einzelne Posten der Rechnung &ndash; und der einzige, der sich
ohne erfundene Kennwerte aus dem Datenblatt herleiten laesst: dort steht die
Bohrung dn des Anschlusselements.</p>
<p>Gerechnet wird als Stroemung durch eine Blende. Massgeblich ist das
Druckverhaeltnis:</p>
""" + _formula(
    "Druckverhaeltnis     pi = (p_0 - dp) / p_0",
    "",
    "kritischer Wert      pi_krit = (2 / (kappa + 1))^(kappa / (kappa - 1))",
    "                             = 0,5283          fuer Luft",
) + """
<p>Bei &minus;0,6&nbsp;bar ist <code>pi = 0,408 &lt; 0,528</code> &ndash; die
Stroemung ist <b>gesperrt</b>, der Massenstrom haengt nur noch vom Vordruck
ab:</p>
""" + _formula(
    "gesperrt (pi <= pi_krit):",
    "",
    "  m_dot = Cd * A * p0 * sqrt( kappa / (R * T) )",
    "                      * (2 / (kappa + 1))^( (kappa+1) / (2*(kappa-1)) )",
    "",
    "",
    "unterkritisch  (pi > pi_krit):",
    "",
    "  m_dot = Cd * A * p0 * sqrt( 2*kappa / ((kappa-1) * R * T)",
    "                              * ( pi^(2/kappa) - pi^((kappa+1)/kappa) ) )",
    "",
    "",
    "  Cd    Ausflussbeiwert (Modellannahme, Vorgabe 0,8)",
    "  A     engster Querschnitt        [m2]",
    "  p0    Umgebungsdruck             [Pa]",
    "  R     Gaskonstante Luft          287,058 J/(kg*K)",
    "  T     Temperatur                 293,15 K",
) + """
<p>Der Massenstrom wird ueber die Umgebungsdichte in einen Volumenstrom
umgerechnet &ndash; das ist die Groesse, mit der Pumpenkennlinien angegeben
werden:</p>
""" + _formula(
    "Q = m_dot / rho_Luft            [m3/s]",
) + """
<h3>Groessenordnung</h3>
<p>Bei Cd&nbsp;=&nbsp;0,8, 20&nbsp;&deg;C und &minus;0,6&nbsp;bar:</p>
<table>
<tr><th>Bohrung dn</th><th>Sauger</th><th>Fremdluft je offenem Sauger</th></tr>
<tr><td>4,0 mm</td><td>SPB2 20 / 25 / 30</td><td>rund 7 m3/h</td></tr>
<tr><td>6,1 mm</td><td>SPB2 40 / 50</td><td>rund 17 m3/h</td></tr>
</table>
<div class="warn">Das uebersteigt die Leistung vieler Vakuumerzeuger. Wenige
offene Sauger koennen das Vakuum der ganzen Platte zusammenbrechen lassen.
Strombegrenzer und Rueckschlagventile sind deshalb der Regelfall, nicht die
Ausnahme.</div>

<h3>Absperrung je Saugerposition</h3>
""" + _formula(
    "ohne Begrenzung     A = pi/4 * dn^2",
    "Drossel             A = min(pi/4 * dn^2, pi/4 * d_Drossel^2)",
    "Rueckschlagventil   A = pi/4 * dn^2 * Restleckage-Anteil",
) + """
<p>Kein Ventil schliesst vollstaendig; die Restleckage ist als Flaechenanteil
modelliert. Alle Angaben dazu stammen aus der Konfiguration, nicht aus dem
Datenblatt.</p>
""" + _source("app/engines/vacuum/flow.py", "orifice_flow_m3s(), orifice_area_mm2()") + """

<h2>Kartonpermeabilitaet</h2>
<p>Die Permeabilitaet ist keine Naturkonstante und wird hier auch nicht als
solche behandelt: der Benutzer gibt sie vor, das Modell bestimmt nur, wie
daraus ein Volumenstrom wird. Vier Modelle, jedes mit eigener Einheit fuer den
eingegebenen Wert:</p>
""" + _formula(
    "dicht               Q = 0",
    "",
    "konstant            Q = k * n_wirksam",
    "                    [k in l/min je wirksamem Sauger]",
    "",
    "je Flaeche          Q = k * A_eff/100 * (dp / dp_Bezug)^n",
    "                    [k in l/min je cm2 beim Bezugsdruck]",
    "                    [n = 1 laminar, n = 0,5 turbulent]",
    "",
    "druckproportional   Q = k * A_eff/100 * dp / 1000",
    "                    [k in l/min je cm2 und 1000 Pa]",
) + """
<p>Welche Einheit gilt, steht in der Oberflaeche neben dem Eingabefeld. Ohne
diese Angabe waere die Zahl bedeutungslos.</p>
""" + _source("app/engines/vacuum/leakage.py", "die vier Modellklassen") + """

<h2>Pumpenkennlinie</h2>
""" + _formula(
    "mit Stuetzpunkten   lineare Interpolation zwischen (dp_i, Q_i)",
    "",
    "ohne Stuetzpunkte   Q(dp) = Q_nenn * (1 - dp / dp_max)",
) + """
<div class="note">Die Gerade ist eine grobe Naeherung &ndash; reale Ejektoren
knicken frueher ein. Sie wird im Rechenweg als Annahme vermerkt, damit niemand
sie fuer eine Herstellerkennlinie haelt. Wer die echte Kennlinie hat, traegt
sie als Stuetzpunkte in <code>vacuum_defaults.json</code> ein.</div>

<h2>Der Arbeitspunkt</h2>
<p>Die naheliegende Rechnung waere: Sollvakuum annehmen, Kraft daraus
bestimmen, benoetigten Volumenstrom danebenstellen und bei Ueberschreitung
warnen. Sie liefert ein Ergebnis, das als sicher ausgewiesen wird, obwohl es nie
eintritt &ndash; schafft der Erzeuger den Strom nicht, stellt sich das
Sollvakuum eben nicht ein.</p>
<p>Gerechnet wird deshalb der Schnittpunkt zweier Kurven:</p>
""" + _formula(
    "Bedarf    Q_b(dp) = Q_offen(dp) + Q_teilweise(dp) + Q_Karton(dp)",
    "                    steigt mit dp",
    "",
    "Angebot   Q_a(dp) = Kennlinie des Erzeugers",
    "                    faellt mit dp",
    "",
    "gesucht   dp*  mit  Q_a(dp*) = Q_b(dp*)",
) + """
<p>Gesucht per Bisektion: <code>Q_a &minus; Q_b</code> ist bei
dp&nbsp;=&nbsp;0 positiv (kein Druckgefaelle, also keine Leckage) und beim
Sollwert negativ. Fuenfzig Halbierungsschritte ergeben eine Genauigkeit weit
unterhalb jeder Messbarkeit.</p>
""" + _formula(
    "lo = 0,  hi = min(dp_soll, dp_max)",
    "",
    "50 mal:   mid = (lo + hi) / 2",
    "          Q_a(mid) >= Q_b(mid)  ->  lo = mid",
    "          sonst                 ->  hi = mid",
    "",
    "dp* = lo",
) + """
<p>Die Haltekraft wird anschliessend bei <b>dp*</b> gerechnet, nicht beim
Sollwert. Ein offener Sauger senkt damit unmittelbar die Traglast, statt nur
eine Warnung zu erzeugen.</p>
<p>Ueber den Schalter <i>Arbeitspunkt loesen</i> laesst sich die einfache
Betrachtung einschalten; beide Zahlen stehen im Ergebnis nebeneinander.</p>
""" + _source("app/engines/vacuum/calculator.py", "_solve_operating_point()")


# 7 Programmatischer Aufbau -----------------------------------------------------

_IMPLEMENTATION = """
<h1>Programmatischer Aufbau</h1>

<h2>Schichten</h2>
<p>Jede Schicht greift nur nach unten. Die Regeln sind nicht nur beschrieben,
sondern werden bei jedem Testlauf am Quelltext geprueft.</p>
""" + _formula(
    "  GUI                Fenster, Tabs, Bedienelemente",
    "   |  DTOs",
    "  SERVICES           oeffentliche Schnittstelle fuer die Oberflaeche",
    "   |",
    "  JOBS / CONFIG      Hintergrundausfuehrung / Konfigurationsdaten",
    "   |",
    "  ENGINES            die Fachlogik - Qt-frei, ohne Dateizugriff",
    "   |",
    "  DTO                unveraenderliche Datenobjekte",
    "   |",
    "  CORE               Einheiten, Fehler, Abbruch, Anfragenummern",
) + """
<table>
<tr><th>Schicht</th><th>darf nicht importieren</th></tr>
<tr><td>core</td><td>alles aus app, Qt</td></tr>
<tr><td>dto</td><td>Qt, alles darueber</td></tr>
<tr><td>engines</td><td>Qt, config, services, jobs, gui &ndash; und keine Datei oeffnen</td></tr>
<tr><td>services</td><td>QtWidgets, QtGui, gui</td></tr>
<tr><td>visualization</td><td>engines, services, gui</td></tr>
<tr><td>gui</td><td>engines, json, Rechenbibliotheken</td></tr>
</table>
""" + _source("tests/test_architecture.py", "prueft diese Tabelle per AST am Quelltext") + """

<h2>Ablauf einer Berechnung</h2>
""" + _formula(
    "Benutzer aendert eine Eingabe",
    "  -> Tab sammelt sie entprellt (200-300 ms)",
    "  -> Tab baut ein DTO und ruft den Service",
    "  -> Service zieht eine Anfragenummer und baut einen Job",
    "  -> JobManager gibt ihn in den Thread-Pool",
    "  -> Engine rechnet, Qt-frei, abbrechbar",
    "  -> Ergebnis-DTO kommt als Qt-Signal zurueck",
    "  -> Service prueft die Anfragenummer",
    "  -> Tab zeigt an",
) + """
<p>Der Oberflaechen-Thread wartet an keiner Stelle auf ein Ergebnis. Es gibt
kein <code>future.result()</code>.</p>

<h2>Schutz vor veralteten Ergebnissen</h2>
<p>Bei entprellter Eingabe laufen mehrere Berechnungen zeitlich ueberlappend
und kommen nicht zwangslaeufig in der Startreihenfolge zurueck &ndash; eine
kleine Palette rechnet schneller als die grosse davor. Zwei Mechanismen, die
zusammengehoeren:</p>
""" + _formula(
    "CancellationToken   bricht ab, was noch laeuft",
    "RequestGate         verwirft, was ueberholt wurde",
) + """
<p>Der Abbruch allein genuegt nicht: zwischen &bdquo;abgebrochen&ldquo; und
&bdquo;Ergebnis liegt bereits im Signalpuffer&ldquo; gibt es ein Zeitfenster,
das sich nicht schliessen laesst. Die Torpruefung beim Empfang schliesst es.</p>
""" + _formula(
    "Anfrage 41 startet",
    "Anfrage 42 startet",
    "Anfrage 41 endet   ->  Ergebnis verwerfen",
    "Anfrage 42 endet   ->  Ergebnis anzeigen",
) + _source("app/core/requests.py", "RequestGate; app/core/cancellation.py") + """

<h2>Nachrechnen statt melden</h2>
<p>Aenderungen an den Paketdaten loesen in beiden Tabs eine neue Berechnung
aus. Solange ein Tab verdeckt ist, wird die Aenderung nur vorgemerkt und beim
Aufschlagen nachgeholt &ndash; Rechenzeit fuer Ergebnisse, die niemand ansieht,
waere verschenkt.</p>
<p>Der zentrale Zustand fuehrt dafuer einen Zaehler, den jede fachliche
Aenderung erhoeht. Jedes Ergebnis merkt sich den Stand, unter dem es entstand;
weichen beide ab, ist die Anzeige ueberholt.</p>
""" + _source("app/services/app_state.py", "AppState.revision, INVALIDATES") + """

<h2>Reproduzierbarkeit</h2>
<p>Gleiche Eingabe, gleiches Ergebnis &ndash; sonst waere ein Palettierplan als
Arbeitsunterlage wertlos. Dafuer noetig:</p>
<ul>
<li>Alle Musterergebnisse werden stabil sortiert (erst nach y, dann nach x).</li>
<li>Bei Gleichstand zweier Kandidaten gewinnt immer der zuerst gepruefte.</li>
<li>Der optionale CP-SAT-Loeser laeuft mit einem Suchfaden und einem
deterministischen Rechenbudget statt eines Zeitlimits nach Uhr. Beides kostet
Loesungsqualitaet; Reproduzierbarkeit ist hier wichtiger.</li>
</ul>

<h2>Leistung</h2>
<table>
<tr><th>Stelle</th><th>Massnahme</th><th>Wirkung</th></tr>
<tr><td>Lastkaskade</td><td>Rasterindex statt jeder-gegen-jeden</td><td>75 s &rarr; 0,9 s bei 148800 Paketen</td></tr>
<tr><td>Lastkaskade</td><td>entfaellt ohne Grenzwert</td><td>vollstaendig</td></tr>
<tr><td>3D-Netz</td><td>Eckpunkte in zwei numpy-Operationen</td><td>36 s &rarr; 0,10 s bei 52800 Paketen</td></tr>
<tr><td>3D-Ansicht</td><td>nur die sichtbare Huelle ab 4000 Koerpern</td><td>52800 &rarr; 8340 Koerper</td></tr>
</table>

<h2>Herkunft der Werte</h2>
<p>Jeder Kennwert der Vakuumrechnung traegt seine Quelle. Die Oberflaeche zeigt
sie im Abschnitt <i>Annahmen</i>:</p>
<table>
<tr><th>Klasse</th><th>Bedeutung</th><th>Beispiel</th></tr>
<tr><td>Datenblatt</td><td>vom Hersteller angegeben</td><td>Saugkraft, Abreisskraft, Geometrie</td></tr>
<tr><td>Konfiguration</td><td>Benutzer- oder Anlagenangabe</td><td>Permeabilitaet, Sicherheitsfaktor, Strombegrenzer</td></tr>
<tr><td>Modellannahme</td><td>Annahme des Rechenmodells</td><td>Ausflussbeiwert, Pumpenkennlinie ohne Stuetzpunkte</td></tr>
</table>
<div class="note">Die theoretischen Saugkraefte des Datenblatts gelten bei
glatter, trockener Oberflaeche und enthalten ausdruecklich <b>keinen</b>
Sicherheitsfaktor. Er wird gesondert angesetzt.</div>
"""


def sections() -> tuple[Section, ...]:
    """Alle Kapitel in Anzeigereihenfolge."""
    return (
        Section("basics", "1. Grundlagen und Einheiten", _BASICS),
        Section("package", "2. Paketdaten", _PACKAGE),
        Section("pallet", "3. Palettierung", _PALLET),
        Section("vacuum_geometry", "4. Vakuum: Geometrie", _VACUUM_GEOMETRY),
        Section("vacuum_force", "5. Vakuum: Kraftmodell", _VACUUM_FORCE),
        Section("vacuum_flow", "6. Vakuum: Stroemung und Arbeitspunkt", _VACUUM_FLOW),
        Section("implementation", "7. Programmatischer Aufbau", _IMPLEMENTATION),
    )


def full_document() -> str:
    """Alle Kapitel als ein HTML-Dokument, mit Sprungmarken."""
    body = "\n".join(
        '<a name="' + section.anchor + '"></a>' + section.html
        for section in sections()
    )
    return "<html><head><style>" + STYLE + "</style></head><body>" + body + "</body></html>"
