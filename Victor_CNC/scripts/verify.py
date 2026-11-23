"""Симуляция: медь заготовки минус рез (из geometry.json или из G-code) -> связность, замыкания, подрез меди."""
import sys, os, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isolation import *
def cut_from_gcode(fn, zmax=-0.01):
    x = y = z = 0; segs = []; mode = None; cur = None
    for l in open(fn):
        l = re.sub(r'\(.*?\)', '', l).strip()
        m = re.match(r'G(\d+)\b', l)
        if not m: continue
        g = int(m.group(1))
        if g not in (0, 1, 2, 3): continue
        v = {k: float(n) for k, n in re.findall(r'([XYZIJ])(-?[\d.]+)', l)}
        nx, ny, nz = v.get('X', x), v.get('Y', y), v.get('Z', z)
        if g == 0 and nz <= 0: raise ValueError('rapid в материале: '+l)
        if nz < zmax or z < zmax:
            if cur is None: cur = [(x, y)]
            if g in (2, 3): cur += _arc((x, y), (nx, ny), (x+v['I'], y+v['J']), g == 2)
            elif (nx, ny) != cur[-1]: cur.append((nx, ny))
        if nz >= zmax and cur:
            if len(cur) > 1: segs.append(LineString(cur))
            cur = None
        x, y, z = nx, ny, nz
    return segs
from gerber_parse import _arc
def check(name, cu, iso, width, pads):
    cut = unary_union([l.buffer(width/2, quad_segs=6) for l in iso])
    bite = cu.intersection(cut)
    board = box(0, 0, W, H)
    rem = [g for g in board.difference(cut).geoms if g.area > 1e-3]
    isl = list(cu.geoms); tr = STRtree(rem)
    owner = {}; split = []
    for i, p in enumerate(isl):
        q = p.buffer(-0.04)
        parts = [g for g in (q.geoms if hasattr(q, 'geoms') else [q]) if g.area > 0.02]
        s = set()
        for g in parts:
            for j in tr.query(g):
                if rem[j].intersection(g).area > 1e-3: s.add(int(j))
        if len(s) > 1: split.append((i, len(s)))
        for j in s: owner.setdefault(j, []).append(i)
    shorts = [v for v in owner.values() if len(v) > 1]
    # минимальный зазор между проводниками после реза
    cond = [rem[j] for j in owner]; t2 = STRtree(cond); mg = 9
    for a, g in enumerate(cond):
        for b in t2.query(g.buffer(0.35)):
            if b > a: mg = min(mg, g.distance(cond[b]))
    print(f'{name}: островов {len(isl)}, замыканий {len(shorts)} {shorts[:5]}, разрывов {len(split)} {split[:5]}, подрез меди {bite.area:.4f} мм2, мин. зазор после реза {mg:.3f} мм, рез {sum(l.length for l in iso):.0f} мм')
    return cut, shorts, split
def drilled(fn):
    x = y = 0; out = {}
    for l in open(fn, encoding='utf-8'):
        if l.startswith('('): continue
        m = dict(re.findall(r'([XYZ])(-?[\d.]+)', l))
        x = float(m.get('X', x)); y = float(m.get('Y', y))
        if l.startswith('G1') and 'Z' in m: out[(x, y)] = min(out.get((x, y), 9), float(m['Z']))
    return out
def check_holes(fn, want):
    """want: {(x, y): глубина}; лишние/пропущенные отверстия и неверная глубина"""
    d = drilled(fn)
    hit = lambda p, S: next((q for q in S if abs(p[0]-q[0]) < .02 and abs(p[1]-q[1]) < .02), None)
    extra = [p for p in d if hit(p, want) is None]
    miss = [p for p in want if hit(p, d) is None]
    bad = [p for p in want if hit(p, d) is not None and abs(d[hit(p, d)] - want[p]) > 1e-3]
    print(f'{os.path.basename(fn)}: отверстий {len(d)}, лишних {len(extra)} {extra[:3]}, пропущено {len(miss)}, неверная глубина {len(bad)}')
if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else None
    geo, res = main()
    for s in ('top', 'bottom'):
        cu, iso = geo[s]
        if src: iso = cut_from_gcode(os.path.join(src, {'top': '01_Top_Isolation_V30.nc', 'bottom': '04_Bottom_Isolation_V30.nc'}[s]))
        for w in (CUT, 0.227): check(f'{s} w={w:.3f}', cu, iso, w, None)
    if src:
        h = res['holes']; t = lambda ks, z: {(p[0], p[1]): z for k in ks for p in h[k]}
        check_holes(os.path.join(src, '02_Drill_0.3_Vias.nc'), t(('via',), -1.85))
        check_holes(os.path.join(src, '03_Drill_1.0_Holes.nc'), {**t(('conn', 'pot'), -2.1), (-6, 20): -6, (W+6, 20): -6})
        qs = {(W-p[0], p[1]): -2.0 for p in h['q']}
        lines = open(os.path.join(src, '05_Contour_2mm.nc'), encoding='utf-8').read().split('(Begin operation: DressupTag)')
        tmp = os.path.join(ROOT, 'build', 'Q_holes_part.nc'); open(tmp, 'w', encoding='utf-8').write(lines[0])
        check_holes(tmp, qs)
        last = lines[1][lines[1].index('Z-1.850'):]
        x = y = z = None; tabs = []
        for l in last.splitlines():
            m = dict(re.findall(r'([XYZ])(-?[\d.]+)', l))
            if not l.startswith('G1') or len(m) < 3: continue
            n = (float(m['X']), float(m['Y']), float(m['Z']))
            if z is not None and n[2] == z and z > -1.6: tabs.append(round(math.hypot(n[0]-x, n[1]-y), 2))
            x, y, z = n
        # полка L по центру фрезы R=1, рампы 45 градусов: сколько материала остаётся (плата 1.6)
        top, R, T = -1.2, 1.0, 1.6
        for L in sorted(set(tabs)):
            print(f'контур: перемычек {tabs.count(L)}, ширина сверху {max(0, L-2*R):.2f}, у низа платы {L-2*R+2*(T+top):.2f}, толщина {min(T+top, T+top-max(0, R-L/2)):.2f} мм')
