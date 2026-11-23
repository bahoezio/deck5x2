"""Zusammenbau v0.3 als GLB (Vorschau): Gehaeuse, Display, ESP mit Dupont-Steckern."""
import math, sys
from pathlib import Path
import numpy as np, trimesh
sys.path.insert(0, str(Path(__file__).resolve().parent))
import unterschale_v03 as U

def box(x0, x1, v0, v1, w0, w1):
    b = trimesh.creation.box(extents=[x1 - x0, v1 - v0, w1 - w0])
    b.apply_translation([(x0 + x1) / 2, (v0 + v1) / 2, (w0 + w1) / 2]); return b

def build(v02_glb, out):
    sc = trimesh.load(v02_glb)
    R = trimesh.transformations.rotation_matrix(math.radians(-12), [1, 0, 0])
    teile = {}
    for n in sc.graph.nodes_geometry:
        if n.endswith("_p") or n.startswith(("unterschale", "schraube", "fuss", "esp_", "feder")): continue
        T, g = sc.graph[n]; m = sc.geometry[g].copy(); m.apply_transform(T); m.apply_transform(R); teile[n] = m
    teile["unterschale"] = U.zu_mesh(U.unterschale())
    ev = (U.ESP_V[0] + U.ESP_V[1]) / 2
    x0, x1 = U.ESP_X; w = U.ESP_UNTEN
    teile["esp_platine"] = box(x0, x1, U.ESP_V[0], U.ESP_V[1], w, w + 1.6)
    teile["esp_modul"] = box(-4.4, 13.6, ev - 9, ev + 9, w + 1.6, w + 4.8)
    teile["esp_usb"] = box(-52.9, -45.5, ev - 10.5, ev - 1.5, w + 1.6, w + 4.8) + box(-52.9, -45.5, ev + 1.5, ev + 10.5, w + 1.6, w + 4.8)
    teile["klebepad"] = box(x0 + 8, x1 - 8, ev - 8, ev + 8, w - U.KLEBEPAD, w)
    st = []
    for side in (-1, 1):
        vc = ev + side * 11.43
        for k in range(22):
            x = x0 + 4.0 + k * 2.54
            st.append(box(x - 1.27, x + 1.27, vc - 1.27, vc + 1.27, w - 2.5 - 14.0, w - 2.5))
    teile["stecker_esp"] = trimesh.util.concatenate(st)
    st = []
    for k in range(14):
        v = -14.27 + 1.27 + k * 2.54
        st.append(box(50.52 - 1.27, 50.52 + 1.27, v - 1.27, v + 1.27, 10.1 - 14.0, 10.1))
    teile["stecker_display"] = trimesh.util.concatenate(st)
    M = U.display_zu_druck()
    out_sc = trimesh.Scene()
    for n, m in teile.items():
        m = m.copy(); m.apply_transform(M); m.merge_vertices(); m.fix_normals(); out_sc.add_geometry(m, node_name=n, geom_name=n)
    zmin = min(g.bounds[0][2] for g in out_sc.geometry.values() if True)
    base = out_sc.geometry["unterschale"].bounds
    for g in out_sc.geometry.values():
        g.apply_translation([0, 0, -base[0][2]])
    out_sc.export(out, include_normals=True)
    return out_sc

if __name__ == "__main__":
    s = build(sys.argv[1], sys.argv[2])
    for n, g in s.geometry.items(): print(n, g.bounds.round(1).tolist())
