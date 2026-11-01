"""Vakuumverlauf ueber der Zeit - wie lange dauert das Absaugen.

Das einzige wirklich neue Stueck Physik gegenueber dem zweiten Tab. Dort
steht, WO sich das Vakuum einpendelt; hier steht, WIE LANGE es dahin braucht.

Die Gleichung
-------------
Alle Volumenstroeme dieser Anwendung sind auf UMGEBUNGSDICHTE bezogen -
Kubikmeter Umgebungsluft je Sekunde, so wie Pumpenkennlinien angegeben werden
(siehe orifice_flow_m3s in physics.py). Mit dieser Festlegung ist die
Massenbilanz des Behaelters einfach:

    Masse im Behaelter     m = rho_umg * (p_abs / p_umg) * V
    Masse je Zeit heraus   rho_umg * ( S(dp) - Q_leck(dp) )

    =>   d(dp)/dt = (p_umg / V) * ( S(dp) - Q_leck(dp) )

Dabei ist dp der Unterdruck gegen die Umgebung (positiv, wie ueberall in
dieser Anwendung), S die Kennlinie des Erzeugers und Q_leck der Bedarf aus
offenen Saugern und Kartondurchlass.

Zwei Eigenschaften machen diese Form brauchbar:

* Sie laeuft GENAU in den Arbeitspunkt, den der zweite Tab anzeigt - dort ist
  S = Q_leck, also d(dp)/dt = 0. Die beiden Tabs koennen sich nicht
  widersprechen, weil sie dieselben zwei Funktionen benutzen.
* Sie ist in dp autonom. Statt die Zeit vorwaerts zu integrieren und mit
  Schrittweiten zu kaempfen, laesst sich die Umkehrung bilden:

        t(dp) = Integral von 0 bis dp  ueber  V / ( p_umg * (S - Q_leck) )

  Das ist eine gewoehnliche Quadratur ueber eine bekannte Funktion. Kein
  Verfahren, das divergieren kann, keine Schrittweitensteuerung.

Angenommen wird dabei: gleichbleibende Temperatur (die Verdichtungswaerme
bleibt aussen vor) und ein Erzeuger, der seine Kennlinie ohne Anlaufzeit
faehrt. Beides macht die gerechnete Zeit eher zu kurz als zu lang.

Warum der Verlauf nie ganz ankommt
----------------------------------
Nahe am Arbeitspunkt geht S - Q_leck gegen null, der Integrand also gegen
unendlich; die Zeit bis zum exakten Endwert ist unendlich. Das ist keine
Schwaeche der Rechnung, sondern die Sache selbst - ein Behaelter erreicht
sein Endvakuum asymptotisch. Gerechnet wird deshalb bis zu einem Anteil
dicht darunter, und ausgewiesen werden die Zeiten bis 90 und 99 Prozent.
"""

from __future__ import annotations

import math

from app.domain.units import STANDARD_AMBIENT_PA
from app.vacuum import physics
from app.vacuum.models import (
    EvacuationCurve, EvacuationPoint, SystemVolumeSpec, VacuumInput, VacuumResult,
)

#: Bis zu welchem Anteil des Arbeitspunkts gerechnet wird.
#:
#: Nicht bis 100 Prozent: dort ist der Integrand unendlich. 99,5 Prozent sind
#: weit jenseits dessen, was eine Anlage unterscheidet, und halten das
#: Integral endlich.
CURVE_LIMIT = 0.995

#: Stuetzstellen des Integrals. 400 Schritte ueber den Unterdruck; der Fehler
#: der Trapezregel liegt damit weit unter einem Prozent der Gesamtzeit.
CURVE_STEPS = 400


def system_volume_m3(plate, volume: SystemVolumeSpec) -> tuple[float, float, float]:
    """(Saugkasten, Schlauch, Zusatz) in Kubikmetern.

    Getrennt und nicht als Summe: welcher der drei Posten die Zeit bestimmt,
    ist die erste Frage, die jemand an diese Rechnung stellt.
    """
    kasten = (
        max(0.0, plate.length_mm) * max(0.0, plate.width_mm)
        * max(0.0, volume.box_height_mm) / 1e9
    )
    radius_m = max(0.0, volume.hose_diameter_mm) / 2000.0
    schlauch = math.pi * radius_m * radius_m * max(0.0, volume.hose_length_m)
    zusatz = max(0.0, volume.extra_volume_l) / 1000.0
    return kasten, schlauch, zusatz


def curve(
    request: VacuumInput,
    result: VacuumResult,
    volume: SystemVolumeSpec,
    frequency_hz: float = physics.REFERENCE_FREQUENCY_HZ,
) -> EvacuationCurve:
    """Der Vakuumverlauf dieser Platte bei dieser Frequenz.

    Gerechnet wird auf dem fertigen Ergebnis des zweiten Tabs: wie viele
    Sauger tragen, wie viele offen sind und wie gross die wirksame Flaeche
    ist, steht dort bereits. Der Verlauf zaehlt nichts nach.
    """
    hinweise: list[str] = []
    kasten, schlauch, zusatz = system_volume_m3(request.plate, volume)
    gesamt = kasten + schlauch + zusatz

    pumpe = physics.pump_at_frequency(request.pump, frequency_hz)
    umgebung = request.ambient_pa or STANDARD_AMBIENT_PA

    # Dieselben Zahlen wie die Platte nebenan: tragende und leckende Sauger
    # stehen im Ergebnis, sie werden hier nicht neu bestimmt.
    tragend = result.sealed_count + (
        result.partial_count if request.count_partial_as_sealed else 0
    )
    leckend = result.open_count + (
        0 if request.count_partial_as_sealed else result.partial_count
    )

    def bedarf(vakuum_pa: float) -> float:
        return physics.demand_m3s(
            cup=request.cup,
            restrictor=request.restrictor,
            leakage=request.leakage,
            vacuum_pa=vakuum_pa,
            ambient_pa=umgebung,
            effective_area_mm2=result.effective_area_mm2,
            bearing_count=tragend,
            leaking_count=leckend,
        )[2]

    decke = min(request.target_vacuum_pa, pumpe.max_vacuum_pa)
    if decke <= 0.0:
        decke = pumpe.max_vacuum_pa
    ende = physics.balance_vacuum_pa(pumpe, decke, bedarf)

    if gesamt <= 0.0:
        hinweise.append(
            "Ohne Systemvolumen gibt es keine Zeitachse - Saugkastenhoehe, "
            "Schlauchlaenge oder Zusatzvolumen eintragen."
        )
        return EvacuationCurve(
            box_volume_m3=kasten, hose_volume_m3=schlauch, extra_volume_m3=zusatz,
            frequency_hz=frequency_hz, nominal_flow_m3s=pumpe.nominal_flow_m3s,
            max_vacuum_pa=pumpe.max_vacuum_pa, final_vacuum_pa=ende,
            notes=tuple(hinweise),
        )
    if ende <= 0.0:
        hinweise.append(
            "Der Erzeuger kommt gegen die Leckage nicht an - es baut sich "
            "kein Vakuum auf."
        )
        return EvacuationCurve(
            box_volume_m3=kasten, hose_volume_m3=schlauch, extra_volume_m3=zusatz,
            frequency_hz=frequency_hz, nominal_flow_m3s=pumpe.nominal_flow_m3s,
            max_vacuum_pa=pumpe.max_vacuum_pa, final_vacuum_pa=ende,
            notes=tuple(hinweise),
        )

    if ende < request.target_vacuum_pa - 1.0:
        hinweise.append(
            "Bei " + format(frequency_hz, ".0f") + " Hz stellt sich der "
            "Arbeitspunkt bei " + format(ende / 100.0, ".0f") + " mbar ein, "
            "das Sollvakuum von " + format(request.target_vacuum_pa / 100.0, ".0f")
            + " mbar wird nicht erreicht."
        )

    faktor = umgebung / gesamt
    schrittweite = ende * CURVE_LIMIT / CURVE_STEPS

    punkte: list[EvacuationPoint] = []
    zeit = 0.0
    vorher = None
    for schritt in range(CURVE_STEPS + 1):
        vakuum = schritt * schrittweite
        angebot = physics.pump_flow_m3s(pumpe, vakuum)
        leck = bedarf(vakuum)
        netto = angebot - leck
        # Trapezregel ueber 1/(S - Q). Der Nenner ist auf dem ganzen Weg
        # positiv - der Nulldurchgang IST der Endwert, und bis dahin wird
        # nicht gerechnet.
        steigung = 1.0 / netto if netto > 0.0 else None
        if vorher is not None and steigung is not None:
            zeit += schrittweite * (vorher + steigung) / (2.0 * faktor)
        vorher = steigung
        punkte.append(EvacuationPoint(
            time_s=zeit, vacuum_pa=vakuum,
            pump_flow_m3s=angebot, leak_m3s=leck,
        ))

    return EvacuationCurve(
        points=tuple(punkte),
        box_volume_m3=kasten, hose_volume_m3=schlauch, extra_volume_m3=zusatz,
        frequency_hz=frequency_hz,
        nominal_flow_m3s=pumpe.nominal_flow_m3s,
        max_vacuum_pa=pumpe.max_vacuum_pa,
        final_vacuum_pa=ende,
        time_to_90_s=_time_at(punkte, ende * 0.90),
        time_to_99_s=_time_at(punkte, ende * 0.99),
        notes=tuple(hinweise),
    )


def _time_at(punkte: list[EvacuationPoint], vakuum_pa: float) -> float:
    """Wann der Verlauf diesen Unterdruck erreicht - linear dazwischen."""
    for vorher, nachher in zip(punkte, punkte[1:]):
        if nachher.vacuum_pa >= vakuum_pa:
            spanne = nachher.vacuum_pa - vorher.vacuum_pa
            if spanne <= 0.0:
                return nachher.time_s
            anteil = (vakuum_pa - vorher.vacuum_pa) / spanne
            return vorher.time_s + anteil * (nachher.time_s - vorher.time_s)
    return punkte[-1].time_s if punkte else 0.0
