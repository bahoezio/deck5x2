"""Deck 5x2 - Unterschale v0.3 (30 Grad Neigung, ESP auf mittiger Auflage, Platz fuer Dupont-Stecker).

Erzeugt:
  hardware/deck_v03_2_gehaeuse.3mf   Oberschale (unveraendert aus v0.2) + neue Unterschale, druckfertig gelegt
  hardware/src/vorschau_v03.glb      Zusammenbau mit Display und ESP als Vorschau

Koordinaten fuer die Konstruktion ("Display-System"):
  x = Breite (links/rechts), v = entlang der Neigung (vorne -> hinten), w = senkrecht zum Display (nach oben)
  w = 14.2 ist die Trennflaeche zwischen Ober- und Unterschale.

Benoetigt: pip install trimesh manifold3d numpy
"""
import math
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import CrossSection, JoinType, Manifold
import manifold3d as m3

HERE = Path(__file__).resolve().parent
HW = HERE.parent

# ---------------------------------------------------------------------------- Parameter
NEIGUNG = 30.0            # Grad gegenueber dem Tisch
VORNE = 18.0              # Dicke der Unterschale vorne (senkrecht zum Display), Platz fuer Stecker am Display
WAND = 2.4
BODEN = 2.4

W_TRENN = 14.2            # Trennflaeche
FASE = 0.5                # Schattenfuge (Fase oben an der Kante)
AUSSEN = (114.0, 68.0, 6.03)           # Breite, Tiefe, Eckradius
V_MITTE = 3.53                         # Mitte in v-Richtung

PLATINE = (108.64, 62.34, 1.0)         # Tasche fuer die Display-Platine (108,04 x 61,74 + 0,3 Luft)
PLATINE_W = 12.6                       # Unterseite der Display-Platine
AUFLAGE = (105.98, 59.95, 1.5)         # Oeffnung unter der Platine -> 1,3 mm Auflagerand

SCHRAUBEN = [(-50.62, -23.94), (50.62, -23.94), (-50.62, 31.0), (50.62, 31.0)]
DOM_D = 9.0
LOCH_D = 3.4              # M3 Durchgang
KOPF_D = 6.4              # Schraubenkopf + Inbus
KOPF_W = 10.0             # Auflage des Schraubenkopfs (M3x8 endet bei w = 18 im Gewindeeinsatz)

# Stiftleiste am Display (rechts): hier keine Auflage, Stecker haengen nach unten
STIFTLEISTE = (49.0, 54.3, -16.5, 23.5)        # x von/bis, v von/bis

# ESP32-S3 DevKitC (69 x 25,4 mm), parallel zum Display, USB-Buchsen zur linken Wand
ESP_X = (-52.4, 16.6)
ESP_V = (-1.5, 24.5)                  # etwas nach vorne, damit die hinteren Stecker die Rueckwand nicht beruehren
ESP_UNTEN = 3.6                       # Unterseite der ESP-Platine
KLEBEPAD = 1.0                        # doppelseitiges Klebepad zwischen Auflage und ESP
ESP_AUFLAGE_B = 18.0                  # nur in der Mitte, die Stiftleisten bleiben frei
USB_SCHLITZ = (-0.2, 23.2, 3.1, 10.5)  # v von/bis, w von/bis

FUSS_D, FUSS_T = 8.4, 0.8
RUECKWAND_SENKRECHT = True            # Rueckwand fast senkrecht, oben buendig mit der Oberschale
RUECKWAND_NEIGUNG = 15.0              # Grad: unten etwas weiter hinten (Platz fuer die Stecker, steht stabiler)             # Vertiefungen fuer Gummifuesse

T = math.tan(math.radians(NEIGUNG))
V_VORNE = V_MITTE - AUSSEN[1] / 2


def rrect(w, h, r, cx=0.0, cy=0.0, seg=64):
    """Rechteck mit runden Ecken, Mitte (cx, cy)."""
    return CrossSection.square([w - 2 * r, h - 2 * r], center=True).offset(r, JoinType.Round, 2, seg).translate([cx, cy])


def prisma(cs, w0, w1):
    return Manifold.extrude(cs, w1 - w0).translate([0, 0, w0])


def boden_ebene(versatz=0.0):
    """Halbraum oberhalb der Tischflaeche (+ versatz entlang der Flaechennormalen)."""
    n = np.array([0.0, T, 1.0]) / math.sqrt(1 + T * T)          # zeigt ins Gehaeuse
    p = np.array([0.0, V_VORNE, W_TRENN - VORNE])               # vordere Unterkante liegt auf dem Tisch
    big = Manifold.cube([1000, 1000, 1000], center=True).translate([0, 0, 500])
    # Wuerfel so drehen, dass seine Unterseite die Ebene ist
    ang = math.degrees(math.atan2(n[1], n[2]))
    return big.rotate([-ang, 0, 0]).translate((p + n * versatz).tolist())


def halbraum(n, d):
    """Alle Punkte p mit n . p <= d (n wird normiert), n liegt in der y-z-Ebene."""
    n = np.asarray(n, float); L = np.linalg.norm(n); n = n / L; d = d / L
    a = math.degrees(math.atan2(-n[1], n[2]))
    big = Manifold.cube([1000, 1000, 1000], center=True).translate([0, 0, -500])
    return big.rotate([a, 0, 0]).translate((n * d).tolist())


def rueckwand(innen=0.0):
    """Halbraum vor der Rueckwand: oben buendig mit der Oberschale, nach unten um RUECKWAND_NEIGUNG nach hinten."""
    th = math.atan(T)
    tb = math.tan(math.radians(RUECKWAND_NEIGUNG))
    n = np.array([0.0, math.cos(th) + math.sin(th) * tb, -math.sin(th) + math.cos(th) * tb])
    p = np.array([0.0, V_MITTE + AUSSEN[1] / 2, W_TRENN - FASE])
    return halbraum(n, float(n @ p) - innen * np.linalg.norm(n))


def unterschale():
    aw, ah, ar = AUSSEN
    aussen = prisma(rrect(aw, ah, ar, 0, V_MITTE), -200, W_TRENN - FASE)
    fase = Manifold.hull(prisma(rrect(aw, ah, ar, 0, V_MITTE), W_TRENN - FASE - 0.01, W_TRENN - FASE) +
                         prisma(rrect(aw - 2 * FASE, ah - 2 * FASE, ar - FASE, 0, V_MITTE), W_TRENN - 0.01, W_TRENN))
    huelle = (aussen + fase) ^ boden_ebene(0)

    # Innenraum
    innen = rrect(aw - 2 * WAND, ah - 2 * WAND, ar - WAND, 0, V_MITTE)
    auflage = rrect(AUFLAGE[0], AUFLAGE[1], AUFLAGE[2], 0, V_MITTE + 0.01)
    raum = prisma(innen, -200, 9.4) + Manifold.hull(prisma(innen, 9.39, 9.4) + prisma(auflage, 11.0, 11.01)) \
        + prisma(auflage, 11.0, PLATINE_W + 0.1)
    raum = raum ^ boden_ebene(BODEN)
    if RUECKWAND_SENKRECHT:
        raum = raum ^ rueckwand(WAND)
    tasche = prisma(rrect(PLATINE[0], PLATINE[1], PLATINE[2], 0, V_MITTE + 0.01), PLATINE_W, W_TRENN + 1)
    x0, x1, v0, v1 = STIFTLEISTE
    stift = Manifold.cube([x1 - x0, v1 - v0, 6]).translate([x0, v0, PLATINE_W - 5.9])
    teil = huelle - raum - tasche - stift

    # Schraubendome (Schraube von unten durch die Display-Platine in den Gewindeeinsatz der Oberschale)
    for (x, v) in SCHRAUBEN:
        dom = Manifold.cylinder(300, DOM_D / 2, DOM_D / 2, 48).translate([x, v, PLATINE_W - 300])
        teil = teil + (dom ^ aussen ^ boden_ebene(0))
    for (x, v) in SCHRAUBEN:
        teil = teil - Manifold.cylinder(400, LOCH_D / 2, LOCH_D / 2, 32).translate([x, v, -380])
        teil = teil - Manifold.cylinder(400, KOPF_D / 2, KOPF_D / 2, 32).translate([x, v, KOPF_W - 400])

    # ESP: Auflage nur in der Mitte (18 mm), Anschlag am rechten Ende
    ev = (ESP_V[0] + ESP_V[1]) / 2
    top = ESP_UNTEN - KLEBEPAD
    sockel = Manifold.cube([ESP_X[1] - 3.0 - (ESP_X[0] + 3.0), ESP_AUFLAGE_B, 300]) \
        .translate([ESP_X[0] + 3.0, ev - ESP_AUFLAGE_B / 2, top - 300])
    anschlag = Manifold.cube([2.5, 12.0, 300]).translate([ESP_X[1] + 0.3, ev - 6.0, ESP_UNTEN + 2.0 - 300])
    fuss_esp = Manifold.cube([ESP_X[1] + 2.8 - (ESP_X[1] - 3.0), ESP_AUFLAGE_B, 300]) \
        .translate([ESP_X[1] - 3.0, ev - ESP_AUFLAGE_B / 2, top - 300])
    teil = teil + ((sockel + anschlag + fuss_esp) ^ aussen ^ boden_ebene(0))

    # USB-Schlitz in der linken Wand (beide Buchsen: USB und COM)
    sv0, sv1, sw0, sw1 = USB_SCHLITZ
    sv0, sv1 = sv0 + ESP_V[0] + 1.47, sv1 + ESP_V[0] + 1.47
    r = (sw1 - sw0) / 2
    wm = (sw0 + sw1) / 2
    rolle = Manifold.cylinder(8.0, r, r, 48).rotate([0, 90, 0])            # Achse entlang x
    schlitz = Manifold.hull(rolle.translate([-61.0, sv0 + r, wm]) + rolle.translate([-61.0, sv1 - r, wm]))
    teil = teil - schlitz
    if RUECKWAND_SENKRECHT:
        teil = teil ^ rueckwand()
    return teil


# ---------------------------------------------------------------------------- Transformationen
def display_zu_druck():
    """Display-System -> Drucklage der Unterschale (Tischflaeche auf z = 0)."""
    ang = math.degrees(math.atan(T))
    M = trimesh.transformations.rotation_matrix(math.radians(ang), [1, 0, 0])
    return M


def zu_mesh(m: Manifold) -> trimesh.Trimesh:
    g = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(g.vert_properties)[:, :3], faces=np.asarray(g.tri_verts), process=True)


def main():
    teil = unterschale()
    mesh = zu_mesh(teil)
    M = display_zu_druck()
    druck = mesh.copy()
    druck.apply_transform(M)
    druck.apply_translation([-druck.bounds[0][0] - (druck.bounds[1][0] - druck.bounds[0][0]) / 2,
                             -druck.bounds[0][1] - (druck.bounds[1][1] - druck.bounds[0][1]) / 2,
                             -druck.bounds[0][2]])

    # Fuesse: Vertiefungen in der Bodenflaeche (z = 0)
    # Standflaeche bestimmen (die Vorderkante ist unterschnitten) und Fuesse innen an die Ecken setzen
    sec = druck.section(plane_origin=[0, 0, 0.05], plane_normal=[0, 0, 1])
    fx0, fy0, fx1, fy1 = sec.bounds[0][0], sec.bounds[0][1], sec.bounds[1][0], sec.bounds[1][1]
    fm = [(-38.0, fy0 + 8.0), (38.0, fy0 + 8.0), (fx0 + 11.0, fy1 - 9.0), (fx1 - 11.0, fy1 - 9.0)]
    mm = m3.Mesh(vert_properties=np.asarray(druck.vertices, dtype=np.float32), tri_verts=np.asarray(druck.faces, dtype=np.uint32))
    d_man = Manifold(mm)
    for fx, fy in fm:
        d_man = d_man - Manifold.cylinder(FUSS_T * 2, FUSS_D / 2, FUSS_D / 2, 48).translate([fx, fy, -FUSS_T])
    druck = zu_mesh(d_man)

    oben = list(trimesh.load(HW / "deck_v02_2_gehaeuse.3mf").geometry.values())[0]
    oben = oben.copy()
    oben.apply_translation([-oben.bounds[:, 0].mean(), -oben.bounds[:, 1].mean() - 50, 0])
    druck.apply_translation([0, 45, 0])

    sc = trimesh.Scene()
    sc.add_geometry(oben, node_name="oberschale", geom_name="oberschale")
    sc.add_geometry(druck, node_name="unterschale", geom_name="unterschale")
    (HW / "deck_v03_2_gehaeuse.3mf").write_bytes(trimesh.exchange.threemf.export_3MF(sc))

    print("Unterschale:", druck.extents.round(1), "dicht:", druck.is_watertight, "Volumen cm3:", round(druck.volume / 1000, 1))
    print("Fuesse:", [(round(x, 1), round(y, 1)) for x, y in fm])
    return mesh, M


if __name__ == "__main__":
    main()
