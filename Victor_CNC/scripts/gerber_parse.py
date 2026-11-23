"""Минимальный парсер Gerber RS-274X / Excellon (EasyEDA Pro) -> shapely."""
import re, os, math
from shapely.geometry import Polygon, Point, LineString, box, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity
from shapely.validation import make_valid

def _arc(p0, p1, c, cw, n=8):
    a0 = math.atan2(p0[1]-c[1], p0[0]-c[0]); a1 = math.atan2(p1[1]-c[1], p1[0]-c[0])
    r = math.hypot(p0[0]-c[0], p0[1]-c[1])
    if cw:
        if a1 >= a0 - 1e-9: a1 -= 2*math.pi
    else:
        if a1 <= a0 + 1e-9: a1 += 2*math.pi
    k = max(3, int(abs(a1-a0)/math.radians(n))+1)
    pts = [(c[0]+r*math.cos(a0+(a1-a0)*i/k), c[1]+r*math.sin(a0+(a1-a0)*i/k)) for i in range(1, k)]
    return pts + [p1]

def parse_gerber(fn):
    """-> список (polarity, geometry, kind, aperture) """
    txt = open(fn, encoding='utf-8', errors='replace').read()
    aps, out = {}, []
    x = y = 0.0; D = None; mode = 1; region = False; pol = 'D'
    reg = []; cur = []
    sc = 1e5; trk = []
    def flush_trk():
        nonlocal trk
        if len(trk) > 1 and D in aps:
            s, d = aps[D]
            out.append((pol, LineString(trk).buffer(d[0]/2, quad_segs=16), 'track', D))
        trk = []
    for m in re.finditer(r'%([^%]*)%|([^*%]*)\*', txt):
        if m.group(1) is not None:
            e = m.group(1).strip()
            a = re.match(r'ADD(\d+)([CRO]),([\dX.]+)\*', e)
            if a:
                aps[int(a.group(1))] = (a.group(2), [float(v) for v in a.group(3).split('X')]); continue
            f = re.match(r'FSLAX(\d)(\d)Y', e)
            if f: sc = 10**int(f.group(2)); continue
            if e.startswith('LP'): pol = e[2]; continue
            if e.startswith('MO') and 'MM' in e: continue
            if e.startswith('AD'): raise ValueError('aperture '+e)
            continue
        c = m.group(2).strip()
        if not c or c.startswith('G04'): continue
        if c == 'G36': flush_trk(); region = True; reg = []; cur = []; continue
        if c == 'G37':
            if len(cur) > 2: reg.append(cur)
            polys = [make_valid(Polygon(r)) for r in reg]
            g = polys[0] if polys else Polygon()
            for p in polys[1:]: g = g.symmetric_difference(p)
            out.append((pol, g, 'region', None)); region = False; cur = []; continue
        a = re.match(r'(?:G54)?D(\d+)$', c)
        if a and int(a.group(1)) >= 10: flush_trk(); D = int(a.group(1)); continue
        g = re.match(r'G0?([123])', c)
        if g: mode = int(g.group(1)); c = c[g.end():]
        if not c or c in ('G75', 'M02') or c.startswith('G7'): continue
        v = {k: int(n)/sc for k, n in re.findall(r'([XYIJ])([+-]?\d+)', c)}
        d = re.search(r'D0?([123])$', c)
        if not v and not d: continue
        op = int(d.group(1)) if d else 1
        nx, ny = v.get('X', x), v.get('Y', y)
        if op == 2:
            if region:
                if len(cur) > 2: reg.append(cur)
                cur = [(nx, ny)]
            else: flush_trk(); trk = [(nx, ny)]
        elif op == 1:
            tgt = cur if region else trk
            if not tgt: tgt.append((x, y))
            if mode == 1: tgt.append((nx, ny))
            else: tgt.extend(_arc((x, y), (nx, ny), (x+v.get('I', 0), y+v.get('J', 0)), mode == 2))
        else:
            flush_trk(); s, dim = aps[D]
            if s == 'C': gg = Point(nx, ny).buffer(dim[0]/2, quad_segs=24)
            elif s == 'R': gg = box(nx-dim[0]/2, ny-dim[1]/2, nx+dim[0]/2, ny+dim[1]/2)
            else:
                w, h = dim; r = min(w, h)/2
                gg = (LineString([(nx-(w/2-r), ny), (nx+(w/2-r), ny)]) if w > h else LineString([(nx, ny-(h/2-r)), (nx, ny+(h/2-r))])).buffer(r, quad_segs=16)
            out.append((pol, gg, 'flash', D))
        x, y = nx, ny
    flush_trk()
    return out

def merge(items):
    g = Polygon()
    if all(p == 'D' for p, *_ in items): return unary_union([i[1] for i in items])
    for p, s, *_ in items: g = g.union(s) if p == 'D' else g.difference(s)
    return g

def parse_drill(fn):
    """-> список (d, [(x,y)] | [(x1,y1),(x2,y2)] для паза)"""
    t, tools, out = None, {}, []
    for l in open(fn):
        l = l.strip()
        m = re.match(r'T(\d+)C([\d.]+)', l)
        if m: tools[m.group(1)] = float(m.group(2)); continue
        m = re.match(r'T(\d+)$', l)
        if m: t = tools[m.group(1)]; continue
        p = re.findall(r'X([-\d.]+)Y([-\d.]+)', l)
        if p: out.append((t, [(float(a), float(b)) for a, b in p]))
    return out
