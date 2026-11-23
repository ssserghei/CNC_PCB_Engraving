# -*- coding: utf-8 -*-
"""Сборка Victor_PCB.FCStd. Запуск: "FreeCAD.exe" scripts/build_project.py
(нужен GUI - иначе у операций не будет ViewProvider)"""
import os, json, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace(chr(92), '/') if '__file__' in globals() else 'D:/GitHub/FreeCAD/CNC_PCB_Engraving/Victor_CNC'
LOG = open(ROOT + '/build/build.log', 'w', encoding='utf-8')
import time
_T0 = time.time()
def log(*a): print('%6.1f' % (time.time()-_T0), *a, file=LOG, flush=True)
import FreeCAD as App, FreeCADGui as Gui, Part, Sketcher
from FreeCAD import Vector as V


def run():
    g = json.load(open(ROOT + '/build/geometry.json'))
    W, H = g['W'], g['H']; T = 1.6
    doc = App.newDocument('Victor_PCB')
    import Path, Path.Main.Job as PJ, Path.Main.Gui.Job as PJG, Path.Tool.Controller as PTC
    import Path.Op.Gui.Base as OG, Path.Op.Gui.Engrave as GE, Path.Op.Gui.Drilling as GD, Path.Op.Gui.Profile as GP
    import Path.Dressup.Tags as DT, Path.Dressup.Gui.Tags as DGT
    from Path.Tool.camassets import cam_assets
    try: cam_assets.setup()
    except Exception as e: log('cam_assets.setup', e)
    from Path.Tool.toolbit import ToolBit
    from Path.Post.Processor import PostProcessorFactory

    # ---------- модель ----------
    xy = lambda p, z=0: V(p[0], p[1], z)
    grp = {}

    def mkface(w):
        f = Part.Face(w[0])
        if len(w) > 1: f.cutHoles(w[1:])
        return f
    for s, lab in (('top', 'Gerber_Top'), ('bottom', 'Gerber_Bottom_mirrored')):
        G = doc.addObject('App::DocumentObjectGroup', lab)
        cu = doc.addObject('Part::Feature', 'Cu_' + s)
        cu.Shape = Part.makeCompound([
            mkface([Part.makePolygon([xy(p, 0.01) for p in r]) for r in isl]) for isl in g[s]['cu']])
        log('copper', s, round(cu.Shape.Area, 2))
        iso = doc.addObject('Part::Feature', 'Iso_' + s)
        iso.Shape = Part.makeCompound([Part.makePolygon([xy(p) for p in l]) for l in g[s]['iso']])
        cu.Label = 'Copper_' + s; iso.Label = 'Isolation_lines_' + s
        G.addObjects([cu, iso]); grp[s] = (G, cu, iso)
        cu.ViewObject.ShapeColor = (0.85, 0.55, 0.2); cu.ViewObject.DisplayMode = 'Shaded'
        iso.ViewObject.LineColor = (0.1, 0.1, 0.9); iso.ViewObject.PointSize = 1
        cu.ViewObject.Visibility = iso.ViewObject.Visibility = (s == 'top')
    body = doc.addObject('PartDesign::Body', 'PCB_Body')
    plane = [f for f in body.Origin.OriginFeatures if 'XY' in f.Name][0]

    def sketch(name):
        sk = body.newObject('Sketcher::SketchObject', name)
        sk.AttachmentSupport = (plane, ['']); sk.MapMode = 'FlatFace'
        sk.ViewObject.Visibility = False
        return sk
    sk = sketch('Sketch_Outline')
    P = [V(0, 0), V(W, 0), V(W, H), V(0, H)]
    for i in range(4): sk.addGeometry(Part.LineSegment(P[i], P[(i+1) % 4]), False)
    C = Sketcher.Constraint
    for i in range(4): sk.addConstraint(C('Coincident', i, 2, (i+1) % 4, 1))
    for c in (C('Horizontal', 0), C('Horizontal', 2), C('Vertical', 1), C('Vertical', 3),
              C('Coincident', 0, 1, -1, 1), C('DistanceX', 0, 1, 0, 2, W), C('DistanceY', 1, 1, 1, 2, H)):
        sk.addConstraint(c)
    doc.recompute()
    pad = body.newObject('PartDesign::Pad', 'Pad'); pad.Profile = sk; pad.Length = T; pad.Reversed = True
    doc.recompute()
    for name, keys, d in (('Holes_0.3_via_gerber0.8', ('via',), 0.3),
                          ('Holes_1.0_conn_pot', ('conn', 'pot'), 1.0),
                          ('Holes_Q1Q2_2.0_gerber1.7', ('q',), 2.0)):
        s2 = sketch('Sketch_holes'); s2.Label = 'Sketch_' + name
        s2.addGeometry([Part.Circle(xy(p), V(0, 0, 1), d/2) for k in keys for p in g['holes'][k]], False)
        doc.recompute()
        pk = body.newObject('PartDesign::Pocket', 'Pocket'); pk.Profile = s2; pk.Type = 1; pk.Label = name
        doc.recompute()
    body.ViewObject.ShapeColor = (0.75, 0.75, 0.55)
    log('body', body.Shape.isValid(), body.Shape.BoundBox, len(body.Shape.Faces))
    mir = doc.addObject('Part::Mirroring', 'PCB_Body_mirrored'); mir.Source = body
    mir.Normal = V(1, 0, 0); mir.Base = V(W/2, 0, 0); doc.recompute()
    mir.ViewObject.Visibility = False
    log('mir', mir.Shape.isValid(), mir.Shape.BoundBox)

    # ---------- задания ----------
    def job(label, model, tool, nr, hf, vf, nc, desc):
        j = PJ.Create('Job', [model]); j.ViewObject.Proxy = PJG.ViewProvider(j.ViewObject)
        doc.recompute()
        j.Label = label; j.Description = desc
        j.JobType = '2D'; j.PostProcessor = 'grbl'; j.PostProcessorArgs = '--no-show-editor --translate_drill'
        j.PostProcessorOutputFile = ROOT + '/nc/' + nc
        old = list(j.Tools.Group)
        tb = ToolBit.from_file(ROOT + '/ToolBits/' + tool)
        to = tb.attach_to_doc(doc); to.ViewObject.Visibility = False
        tc = PTC.Create('TC: ' + to.Label, tool=to, toolNumber=nr)
        j.Proxy.addToolController(tc)
        for o in old:
            t = o.Tool; o.Tool = None
            j.Tools.removeObject(o); o.setExpression('HorizRapid', None); o.setExpression('VertRapid', None)
            doc.removeObject(o.Name)
            if t:
                bb = getattr(t, 'BitBody', None)
                if bb:
                    bb.removeObjectsFromDocument(); doc.removeObject(bb.Name)
                doc.removeObject(t.Name)
        tc.HorizFeed = hf/60.0; tc.VertFeed = vf/60.0
        tc.setExpression('HorizRapid', None); tc.setExpression('VertRapid', None)
        tc.HorizRapid = 10; tc.VertRapid = 5
        tc.SpindleSpeed = 1000; tc.SpindleDir = 'Forward'
        st = j.Stock
        st.ExtXneg = st.ExtXpos = 12; st.ExtYneg = st.ExtYpos = 8; st.ExtZneg = st.ExtZpos = 0
        doc.recompute()
        st.ViewObject.Visibility = False
        return j, tc

    def op(gui, j, tc, label, start, final, step, clear=5, safe=3):
        log('op', label); r = gui.Command.res; r.job = j
        o = r.objFactory(r.name, obj=None, parentJob=j)
        o.ViewObject.Proxy = OG.ViewProvider(o.ViewObject, r); r.job = None
        o.Label = label; o.ToolController = tc
        for p, v in (('ClearanceHeight', clear), ('SafeHeight', safe), ('StartDepth', start),
                     ('FinalDepth', final), ('StepDown', step)):
            if hasattr(o, p): o.setExpression(p, str(v))
        return o

    def faces(clone, pts, rad):
        cyl = [(i+1, f.Surface) for i, f in enumerate(clone.Shape.Faces) if isinstance(f.Surface, Part.Cylinder)]
        out = []
        for p in pts:
            m = [i for i, s in cyl if abs(s.Radius - rad) < 1e-4 and abs(s.Center.x - p[0]) < 1e-3 and abs(s.Center.y - p[1]) < 1e-3]
            if not m: raise ValueError('hole face not found %s' % p)
            out.append('Face%d' % m[0])
        return out

    def drill(j, tc, label, keys, rad, final, peck, mirrored=False):
        o = op(GD, j, tc, label, 0, final, peck)
        cl = j.Model.Group[0]
        o.Base = [(cl, tuple(faces(cl, [(W-p[0] if mirrored else p[0], p[1]) for k in keys for p in g['holes'][k]], rad)))]
        o.PeckEnabled = True; o.setExpression('PeckDepth', str(peck)); o.setExpression('RetractHeight', '1')
        return o

    jobs = []
    VB, EM = 'v_bit_30gr_0.2mm.fctb', 'endmill_d2mm_h10mm.fctb'
    j, tc = job('1_Isolation_Top', body, VB, 1, 120, 20, '01_Top_Isolation_V30.nc',
                'Верх: изоляция, V-бит 30 гр / 0.2, глубина 0.10 (ширина реза 0.254)'); jobs.append(j)
    o = op(GE, j, tc, 'Engrave_Top', 0, -0.10, 0.10, 1.5, 0.5); o.BaseShapes = [grp['top'][2]]; doc.recompute()

    j, tc = job('2_Drill_0.3_Vias', body, 'drill_d0.3mm.fctb', 3, 30, 30, '02_Drill_0.3_Vias.nc',
                'Сверло 0.3: 32 переходных (в Gerber 0.8)'); jobs.append(j)
    drill(j, tc, 'Drill_Vias_0.3', ('via',), 0.15, -1.85, 0.3); doc.recompute()

    j, tc = job('3_Drill_1.0', body, 'drill_d1.0mm.fctb', 4, 60, 60, '03_Drill_1.0_Holes.nc',
                'Сверло 1.0: разъёмы, клеммы, R20/R21 + 2 отверстия под штифты 1 мм (глубина 6 мм)'); jobs.append(j)
    drill(j, tc, 'Drill_Conn_Pot_1.0', ('conn', 'pot'), 0.5, -2.1, 0.5)
    o = op(GD, j, tc, 'Drill_Align_pins_1.0', 0, -6, 0.5)
    o.Base = []      # при создании операция сама подбирает все отверстия модели
    o.Locations = [V(-6, 20, 0), V(W+6, 20, 0)]
    o.PeckEnabled = True; o.setExpression('PeckDepth', '0.5'); o.setExpression('RetractHeight', '1'); doc.recompute()

    j, tc = job('1_Isolation_Bottom', mir, VB, 1, 120, 20, '04_Bottom_Isolation_V30.nc',
                'Низ, после переворота влево-вправо на штифтах: изоляция'); jobs.append(j)
    o = op(GE, j, tc, 'Engrave_Bottom', 0, -0.10, 0.10, 1.5, 0.5); o.BaseShapes = [grp['bottom'][2]]; doc.recompute()

    j, tc = job('4_Contour', mir, EM, 2, 100, 30, '05_Contour_2mm.nc',
                'Фреза 2 мм: отверстия Q1/Q2, затем контур с перемычками как в HobbyTouristing'); jobs.append(j)
    drill(j, tc, 'Drill_Q1Q2_2mm', ('q',), 1.0, -2.0, 0.4, True)
    o = op(GP, j, tc, 'Profile_Contour', 0, -1.85, 0.3)
    cl = j.Model.Group[0]
    e = ['Edge%d' % (i+1) for i, x in enumerate(cl.Shape.Edges)
         if isinstance(x.Curve, (Part.Line, Part.BSplineCurve)) and abs(x.BoundBox.ZMax + T) < 1e-6 and x.Length > 50]
    log('contour edges', e, [type(cl.Shape.Edges[int(k[4:])-1].Curve) for k in e])
    o.Base = [(cl, tuple(e))]; o.Side = 'Outside'; o.Direction = 'CW'; o.UseComp = True
    doc.recompute(); log('profile cmds', len(o.Path.Commands))
    t = DT.Create(o, 'DressupTag'); t.ViewObject.Proxy = DGT.PathDressupTagViewProvider(t.ViewObject)
    doc.recompute()
    # setup(generate=True) ставит свои Width/Height, поэтому размеры задаются после него
    t.Proxy.setup(t, True)
    t.Width = 2; t.Height = 0.65; t.Angle = 45; t.Radius = 0
    t.Proxy.generateTags(t, 8); t.Proxy.execute(t); doc.recompute()
    log('tag size', t.Width, t.Height, t.Angle, t.Radius)
    log('tags', len(t.Positions), [tuple(round(c, 2) for c in p) for p in t.Positions], len(t.Path.Commands))

    for o in doc.Objects:
        if 'Invalid' in o.State or 'Error' in o.State: log('STATE', o.Name, o.State)
    # ---------- постпроцессинг ----------
    for j in jobs:
        post = PostProcessorFactory.get_post_processor(j, 'grbl')
        for part, gc in post.export():
            with open(j.PostProcessorOutputFile, 'w', encoding='utf-8', newline='\n') as f: f.write(gc)
        log(j.Label, j.CycleTime, [(p.Label, len(p.Path.Commands), round(p.Path.Length)) for p in j.Operations.Group],
            os.path.getsize(j.PostProcessorOutputFile))
    # ---------- вид ----------
    for j in jobs:
        for c in j.Model.Group: c.ViewObject.Visibility = False
        for q in j.Operations.Group: q.ViewObject.Visibility = False
    v = Gui.getDocument(doc.Name).ActiveView; v.viewTop(); Gui.SendMsgToActiveView('ViewFit')

    def show(side, opobj, fn):
        for q in jobs:
            for p in q.Operations.Group: p.ViewObject.Visibility = False
        for s in ('top', 'bottom'):
            grp[s][1].ViewObject.Visibility = (s == side); grp[s][2].ViewObject.Visibility = False
        body.ViewObject.Visibility = side == 'top'; mir.ViewObject.Visibility = side == 'bottom'
        if opobj: opobj.ViewObject.Visibility = True
        Gui.updateGui(); v.saveImage(ROOT + '/build/' + fn, 1800, 1300, 'White')
    show('bottom', jobs[3].Operations.Group[0], 'view_bottom.png')
    show('bottom', jobs[4].Operations.Group[-1], 'view_contour.png')
    show('top', jobs[2].Operations.Group[0], 'view_drill.png')
    show('top', jobs[0].Operations.Group[0], 'view_top.png')
    doc.saveAs(ROOT + '/Victor_PCB.FCStd')
    log('DONE')


def main():
    try: run()
    except Exception: log(traceback.format_exc())
    LOG.close(); os._exit(0)


from PySide import QtCore
QtCore.QTimer.singleShot(1500, main)
