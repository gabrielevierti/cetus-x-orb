#!/usr/bin/env python3
"""Fit-test pieces, plate layout for a 256 mm bed, STL/3MF export.

    python3 src/build.py                 # writes print/stl and print/3mf
    python3 src/build.py --fit 0.16      # looser joints
    python3 src/build.py --fc-screw m2   # M2 instead of M1.4 for FC + deck
"""
import argparse
import json
import math
import os

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon
from manifold3d import CrossSection, Manifold

from orb import (P, PRINT_COUNTS, assembly, cage_2d, frame, print_parts, rect, stand_in_hardware,
                 to_trimesh, union)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BED, MARGIN, GAP = 256.0, 4.0, 3.0


def wedge(r, a0, a1):
    pts = [(0, 0)] + [(r * math.cos(math.radians(t)), r * math.sin(math.radians(t))) for t in np.linspace(a0, a1, 24)]
    return CrossSection([pts])


def to_origin(m):
    bb = m.bounding_box()
    return m.translate([-bb[0], -bb[1], -bb[2]])


def fit_tests(p: P):
    """small cut-outs of the real parts, print these first"""
    fr4 = frame(p).translate([0, 0, p.t_plate])
    fr3 = frame(P(**{**p.__dict__, 'motor_holes': 3})).translate([0, 0, p.t_plate])
    (mx, my, _) = p.motor_xy()[0]
    h = p.fc_spacing / 2

    def box(x0, y0, x1, y1):
        return Manifold.cube([x1 - x0, y1 - y0, 60]).translate([x0, y0, -1])
    holes_cam = union([
        (fr4 ^ box(mx - 9, my - 9, mx + 9, my + 9)).translate([-mx, -my, 0]),          # 4-hole motor pad
        (fr3 ^ box(mx - 9, my - 9, mx + 9, my + 9)).translate([-mx + 21, -my, 0]),     # 3-hole motor pad
        (fr4 ^ box(h - 6, h - 6, h + 6, h + 6)).translate([-h + 42, -h, 0]),           # FC post
        (fr4 ^ box(14.0, -12.0, 25.0, 12.0)).translate([-12.0, 18, 0]),                # camera cradle
    ])
    k = cage_2d(p)
    az = 30.0
    pieces = [
        (k['ring_a'][0] ^ wedge(120, az - 9, az + 9)).extrude(p.ringA_t),
        (k['rib_upper_long'][0] ^ rect(-1, -0.7, 200, 14.0)).extrude(p.rib_t),
        (k['ring_b'][0] ^ wedge(120, az - 12, az + 12)).extrude(p.ringB_t),
        (k['rib_upper_long'][0] ^ rect(-1, p.zB - 9, 200, p.zB + 9)).extrude(p.rib_t),
    ]
    x, placed = 0.0, []
    for m in map(to_origin, pieces):
        bb = m.bounding_box()
        placed.append(m.translate([x, 0, 0]))
        x += bb[3] - bb[0] + 4
    return {'fit_test_holes_camera': to_origin(holes_cam), 'fit_test_joints': union(placed)}


def footprint(m: Manifold):
    geo = None
    for c in m.project().to_polygons():
        pg = Polygon(np.asarray(c)).buffer(0)
        geo = pg if geo is None else geo.symmetric_difference(pg)
    return geo.buffer(0)


def pack(items, rotations=(0, 90, 180, 270, 45, 135, 225, 315), step=2.0):
    """greedy bottom-left packing, parts may land inside the rings"""
    placed, out = [], []
    lo, hi = MARGIN, BED - MARGIN
    for name, m in items:
        best = None
        fp0 = footprint(m)
        for rot in rotations:
            fp = affinity.rotate(fp0, rot, origin=(0, 0))
            bx0, by0, bx1, by1 = fp.bounds
            if bx1 - bx0 > hi - lo or by1 - by0 > hi - lo:
                continue
            fpb = fp.buffer(GAP / 2)
            found = None
            for ty in np.arange(lo - by0, hi - by1 + 1e-6, step):
                for tx in np.arange(lo - bx0, hi - bx1 + 1e-6, step):
                    if not any(affinity.translate(fpb, tx, ty).intersects(q) for q in placed):
                        found = (tx, ty)
                        break
                if found:
                    break
            if found and (best is None or found[1] * 1000 + found[0] < best[0]):
                best = (found[1] * 1000 + found[0], rot, found, fpb)
        if best is None:
            raise SystemExit(f'{name} does not fit')
        _, rot, (tx, ty), fpb = best
        placed.append(affinity.translate(fpb, tx, ty))
        out.append((name, m.rotate([0, 0, rot]).translate([tx, ty, 0])))
    return out


def plates(p: P):
    pr = print_parts(p)
    ft = fit_tests(p)
    plan = {
        'plate0_fit_test': [(k, v) for k, v in ft.items()],
        'plate1_frame_deck_cap_upper_ribs': [('frame', pr['frame']), ('vtx_deck', pr['vtx_deck']), ('pole_cap', pr['pole_cap'])]
        + [(f'rib_upper_long_{i + 1}', pr['rib_upper_long']) for i in range(4)]
        + [(f'rib_upper_short_{i + 1}', pr['rib_upper_short']) for i in range(4)],
        'plate2_rings_a_b_d': [('ring_a', pr['ring_a']), ('ring_b', pr['ring_b']), ('ring_d', pr['ring_d'])],
        'plate3_ring_a_lower_ribs': [('ring_a', pr['ring_a'])] + [(f'rib_lower_{i + 1}', pr['rib_lower']) for i in range(8)],
    }
    return {k: pack(v) for k, v in plan.items()}, pr, ft


def export(p: P, out):
    os.makedirs(f'{out}/stl', exist_ok=True)
    os.makedirs(f'{out}/3mf', exist_ok=True)
    layout, pr, ft = plates(p)
    for k, m in {**pr, **ft}.items():
        to_trimesh(m).export(f'{out}/stl/{k}_x{PRINT_COUNTS.get(k, 1)}.stl')
    p3 = P(**{**p.__dict__, 'motor_holes': 3})
    to_trimesh(print_parts(p3)['frame']).export(f'{out}/stl/frame_3_hole_motors_x1.stl')
    summary = {}
    for k, items in layout.items():
        sc = trimesh.Scene()
        for name, m in items:
            sc.add_geometry(to_trimesh(m), node_name=name, geom_name=name)
        sc.export(f'{out}/3mf/{k}.3mf')
        summary[k] = round(sum(m.volume() for _, m in items) * p.density / 1000, 1)
    # assembled model, only for looking at it
    asm = assembly(p)
    sc = trimesh.Scene()
    for k, m in asm.items():
        sc.add_geometry(to_trimesh(m), node_name=k, geom_name=k)
    for k, m in stand_in_hardware(p).items():
        sc.add_geometry(to_trimesh(m), node_name='ref_' + k, geom_name='ref_' + k)
    sc.export(f'{out}/assembled_reference_DO_NOT_PRINT.3mf')
    return layout, summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--fit', type=float, default=P.fit)
    ap.add_argument('--fc-screw', choices=['m1.4', 'm2'], default='m1.4')
    ap.add_argument('--out', default=os.path.join(ROOT, 'print'))
    a = ap.parse_args()
    kw = {'fit': a.fit}
    if a.fc_screw == 'm2':
        kw.update(fc_pilot_d=1.7, fc_clear_d=2.3)
    layout, summary = export(P(**kw), a.out)
    print(json.dumps(summary, indent=1))
