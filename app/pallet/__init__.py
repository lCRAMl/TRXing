"""Die Palettierung: Lagen legen, stapeln, bewerten.

Nur noch Rechnung. Das Formular, der Tab, die Zeichnung und die 3D-Szene
liegen seit dem 2026-11-01 unter app/gui/pallet/. Was hier steht, kennt
weder Qt noch die Anzeige - mit einer Ausnahme, die keine ist: service.py
benutzt QObject und pyqtSignal, weil ein Signal der einzige threadsichere
Weg aus einem Worker in den Oberflaechen-Thread ist. Ein Bedienelement
kennt es damit nicht.
"""
