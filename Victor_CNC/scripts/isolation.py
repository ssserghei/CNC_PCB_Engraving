"""Изоляция: линия центра V-бита вокруг каждого острова меди (кроме самого большого полигона),
по середине зазора. Результат -> build/geometry.json (координаты: X вправо, Y вверх, 0,0 = левый нижний угол платы)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gerber_parse import *
from shapely.ops import linemerge
from shapely.geometry.polygon import orient
from shapely.geometry import MultiLineString
from shapely import STRtree
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB = os.path.join(ROOT, 'Gerber_PCB1_2026-11-22')
W, H = 99.06, 71.12
TIP, ANGLE, DEPTH = 0.2, 30.0, 0.10           # v_bit_30gr_0.2mm
CUT = TIP + 2*DEPTH*math.tan(math.radians(ANGLE/2))
OFF = 0.149                                    # половина минимального зазора 0.298
SIMP = 0.004

def lines_of(g):
    if g.is_empty: return []
    if g.geom_type in ('LineString', 'LinearRing'): return [LineString(g.coords)]
    return [l for x in g.geoms for l in lines_of(x)]

def isolate(cu):
    isl = sorted(cu.geoms, key=lambda p: -p.area)
    done, tree = [], []
    cutbuf = Polygon()
    out = []
    for p in sorted(isl[1:], key=lambda p: p.area):
        b = p.buffer(OFF, quad_segs=8)
        for poly in (b.geoms if b.geom_type == 'MultiPolygon' else [b]):
            for ring in [poly.exterior, *poly.interiors]:
                l = LineString(ring.coords).simplify(SIMP)
                near = [o for o in out if o.envelope.buffer(0.1).intersects(l.envelope)]
                if near:
                    z = unary_union([o.buffer(0.03) for o in near if o.distance(l) < 0.05]) if any(o.distance(l) < 0.05 for o in near) else None
                    r = l.difference(z) if z is not None else l
                else: r = l
                r = lines_of(r)
                if len(r) > 1:
                    r = lines_of(linemerge(MultiLineString(r)))
                out += [x for x in r if x.length > 0.06]
    return out

def main():
    res = {'W': W, 'H': H, 'cut_width': CUT}
    sh = lambda g: affinity.translate(g, 0, H)
    mir = lambda g: affinity.scale(g, -1, 1, origin=(W/2, 0))
    geo = {}
    for s, f in (('top', 'Gerber_TopLayer.GTL'), ('bottom', 'Gerber_BottomLayer.GBL')):
        cu = sh(merge(parse_gerber(os.path.join(GB, f))))
        if s == 'bottom': cu = mir(cu)         # вид снизу, переворот вокруг вертикальной оси
        iso = isolate(cu)
        geo[s] = (cu, iso)
        res[s] = {'iso': [list(map(list, l.coords)) for l in iso],
                  'cu': [[list(map(list, r.coords)) for r in (q.exterior, *q.interiors)]
                         for q in (orient(p.simplify(0.01)) for p in cu.geoms)]}
        print(s, 'islands', len(cu.geoms), 'paths', len(iso), 'pts', sum(len(l.coords) for l in iso), 'len mm', round(sum(l.length for l in iso)), 'min/F120', round(sum(l.length for l in iso)/120))
    dr = parse_drill(os.path.join(GB, 'Drill_PTH_Through.DRL'))
    via = {tuple(p[0]) for _, p in parse_drill(os.path.join(GB, 'Drill_PTH_Through_Via.DRL'))}
    holes = {'via': [], 'pot': [], 'conn': [], 'q': []}
    for d, p in dr:
        c = (sum(a[0] for a in p)/len(p), sum(a[1] for a in p)/len(p))
        k = 'q' if d > 1.5 else 'pot' if d < 0.79 else 'via' if tuple(p[0]) in via else 'conn'
        holes[k].append([round(c[0], 5), round(c[1]+H, 5)])
    res['holes'] = holes
    print({k: len(v) for k, v in holes.items()})
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, 'build', 'geometry.json'), 'w'))
    return geo, res
if __name__ == '__main__': main()
