"""Картинки сторон (медь после фрезеровки) и список выводов, которым нужна пайка с двух сторон."""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isolation import *
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as MP
from matplotlib.patches import PathPatch, Circle
OUT = os.path.join(ROOT, 'out')
def patch(g, **k):
    v, c = [], []
    for p in (g.geoms if hasattr(g, 'geoms') else [g]):
        for r in (p.exterior, *p.interiors):
            q = list(r.coords); v += q; c += [MP.MOVETO] + [MP.LINETO]*(len(q)-2) + [MP.CLOSEPOLY]
    return PathPatch(MP(v, c), **k)
geo, res = main()
for s, cap in (('top', 'TOP'), ('bottom', 'BOTTOM (mirrored, as milled)')):
    cu, iso = geo[s]
    cut = unary_union([l.buffer(CUT/2, quad_segs=6) for l in iso])
    left = box(-12, -8, W+12, H+8).difference(cut)
    f, ax = plt.subplots(figsize=(13, 9.2), dpi=150)
    ax.add_patch(patch(left, fc='#c98b4a', ec='none'))
    ax.plot(*box(-1, -1, W+1, H+1).exterior.xy, color='#1b6ac9', lw=1, ls='--', label='contour, 2 mm end mill centre line')
    ax.plot(*box(-.5, -.5, W+.5, H+.5).exterior.xy, color="r", lw=.8, label="test pass, V-bit")
    ax.plot(*box(0, 0, W, H).exterior.xy, color='k', lw=0.8, label='board outline 99.06 x 71.12')
    for k, r in (('via', .15), ('pot', .5), ('conn', .5), ('q', 1.0)):
        for x, y in res['holes'][k]: ax.add_patch(Circle((W-x if s == 'bottom' else x, y), r, fc='white', ec='k', lw=.4))
    for x in (-6, W+6): ax.add_patch(Circle((x, 20), .5, fc='white', ec='r', lw=1.2))
    ax.plot([], [], 'o', mfc='white', mec='r', label='alignment pin holes, 1 mm')
    ax.plot(0, 0, '+', color='r', ms=14, mew=2, label='G54 X0 Y0')
    ax.set_xlim(-13, W+13); ax.set_ylim(-9, H+9); ax.set_aspect('equal'); ax.set_title(cap + ': copper after isolation milling')
    ax.legend(loc='upper center', bbox_to_anchor=(.5, -.04), ncol=5, frameon=False); f.tight_layout()
    f.savefig(os.path.join(OUT, s + '_milled.png')); plt.close(f)
j = json.load(open(os.path.join(GB, 'FlyingProbeTesting.json'), encoding='utf8'))
pins = [dict(zip(j['pins']['fields'], r)) for r in j['pins']['rows']]
cuT = list(geo['top'][0].geoms); cuB = list(geo['bottom'][0].geoms); seen = set(); rep = collections.defaultdict(lambda: collections.defaultdict(list))
for p in pins:
    if not p['HOLE_SIZE'] or p['PIN_NAME'] in seen: continue
    seen.add(p['PIN_NAME']); x, y = p['PIN_X']*.0254, p['PIN_Y']*.0254 + H; pad = p['PAD_SIZEX']*p['PAD_SIZEY']*.0254**2
    def big(c, x):
        for g in c:
            if g.contains(Point(x, y)): return g.area > pad*1.15
    t, b = big(cuT, x), big(cuB, W-x)
    rep[p['PIN_NAME'].split('_')[0]]['both' if t and b else 'top' if t else 'bottom' if b else 'none'].append(p['PIN_NAME'].split('_')[1])
for c, v in rep.items(): print(c, {k: ','.join(x) if k != 'none' else len(x) for k, x in v.items()})
