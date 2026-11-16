#!/usr/bin/env python3
"""
Cetus X ORB - parametric model of the printed frame and spherical cage.

Take a stock BetaFPV Cetus X apart, move motors, FC, camera/VTX and the
battery lead onto a printed frame, and close it inside a ~168 mm ball.
Everything prints flat, no supports, on a 256 mm bed.

    python3 src/orb.py              # run the checks
    python3 src/build.py            # write STL/3MF to print/
    python3 src/render.py           # write images to docs/img/

Units are mm. x points forward (camera), y left, z up.
z = 0 is the top face of the frame, where the motors sit.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np
from manifold3d import CrossSection, Manifold, OpType, JoinType


# ---------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------

@dataclass
class P:
    # stock Cetus X hardware --------------------------------------------------
    wheelbase: float = 95.0          # motor-to-motor diagonal. Motor leads are 32 mm, don't stretch it
    prop_d: float = 50.3             # Gemfan 2020 4-blade disc
    prop_z0: float = 10.5            # bottom of the prop above the motor face
    prop_z1: float = 15.0            # top of the prop hub
    motor_bell_d: float = 14.2
    motor_bell_h: float = 10.5
    motor_hole_circle: float = 8.5   # 1103: M1.6 on 8.5 mm
    motor_hole_d: float = 1.9
    motor_holes: int = 4             # 4 or 3, check with the fit test
    motor_hole_rot: float = 45.0
    motor_center_hole: float = 5.5
    motor_pad_d: float = 14.0

    fc_spacing: float = 26.0         # whoop pattern
    fc_board: float = 32.0
    fc_board_t: float = 1.6
    fc_post_d: float = 5.0
    fc_post_h: float = 2.5
    fc_pilot_d: float = 1.2          # M1.4 self-tapping. For M2 use 1.7
    fc_clear_d: float = 1.7          # deck through hole. For M2 use 2.3
    fc_comp_h: float = 1.5

    cam_w: float = 14.0              # nano camera (C04 = Caddx Ant / RunCam Nano 4)
    cam_depth: float = 12.0
    cam_lens_d: float = 9.0
    cam_lens_len: float = 6.0
    cam_x: float = 19.0              # tilt pivot
    cam_z: float = 16.0
    cam_hole_d: float = 1.6          # M1.4 side screw. For M2 use 2.2
    cam_hole_slot: float = 1.6       # vertical slot, +-0.8 mm of play for the camera hole
    cam_plate_t: float = 1.4
    cam_gap: float = 0.25
    cam_tilt_default: float = 25.0

    batt_w: float = 15.5             # BT2.0 450 mAh 1S: 62 x 15.5 x 6.7, 12.7 g
    batt_l: float = 62.0
    batt_t: float = 6.7
    batt_n: int = 2
    batt_x: float = -4.0             # pack sits a bit back to balance the camera
    strap_slot_l: float = 11.0       # 10 mm velcro strap
    strap_slot_w: float = 2.2

    # frame -------------------------------------------------------------------
    t_plate: float = 2.0
    hub_x0: float = -21.0
    hub_x1: float = 16.0
    hub_hw: float = 21.0
    nose_x1: float = 24.0
    nose_hw: float = 9.4
    arm_w: float = 6.0
    arm_wall_t: float = 1.0
    arm_wall_h: float = 3.0
    ext_w: float = 4.5
    ext_rib_t: float = 1.2
    ext_rib_h: float = 3.0
    tab_in: float = 3.2              # M2 hole sits 3.2 mm in from ring A, so the tab stays outside the prop disc
    tip_w: float = 8.5
    clamp_hole_d: float = 2.2

    # vtx deck ----------------------------------------------------------------
    deck_t: float = 1.2
    deck_foot_h: float = 3.0
    deck_foot_d: float = 4.4
    deck_front_x: float = 10.0

    # cage --------------------------------------------------------------------
    R: float = 84.0                  # outer radius of the ball
    zc: float = 11.0                 # ball centre above the frame, keeps the CG low
    rib_d: float = 3.0               # rib depth (radial)
    rib_t: float = 1.6               # rib thickness = print height
    ringA_d: float = 3.4
    ringA_t: float = 1.6
    ringB_lat: float = 48.0
    ringB_t: float = 1.6
    ringB_in: float = 2.4
    ringB_out: float = 1.2
    ringD_lat: float = -52.0         # landing ring
    ringD_t: float = 1.6
    ringD_in: float = 3.0
    ringD_out: float = 1.2
    notch: float = 0.6               # locating notch on the ribs for rings B and D
    rib_az: tuple = (30.0, 75.0, 120.0, 165.0, -165.0, -120.0, -75.0, -30.0)
    long_rib_az: tuple = (30.0, 120.0, -120.0, -30.0)   # these four reach the pole cap
    pole_r_end: float = 5.0
    cap_r: float = 11.0
    cap_t: float = 2.4
    cap_slot_h: float = 1.6
    fit: float = 0.12                # joint clearance per side

    density: float = 1.27            # PETG, g/cm3

    @property
    def r_motor(self):
        return self.wheelbase / 2.0

    def motor_xy(self):
        return [(self.r_motor * math.cos(math.radians(t)), self.r_motor * math.sin(math.radians(t)), t)
                for t in (45.0, 135.0, -135.0, -45.0)]

    @property
    def zA_top(self):
        return self.ringA_t / 2.0

    @property
    def zA_bot(self):
        return -self.t_plate - self.ringA_t / 2.0

    def rho_sphere(self, z, r=None):
        r = self.R if r is None else r
        dz = z - self.zc
        return math.sqrt(max(r * r - dz * dz, 0.0))

    @property
    def rhoA(self):
        # same ring printed twice, so use the mean of the two heights
        return 0.5 * (self.rho_sphere(self.zA_top) + self.rho_sphere(self.zA_bot))

    @property
    def r_screw(self):
        return self.rhoA - self.ringA_d - self.tab_in

    @property
    def zB(self):
        return self.zc + self.R * math.sin(math.radians(self.ringB_lat))

    @property
    def zD(self):
        return self.zc + self.R * math.sin(math.radians(self.ringD_lat))

    def rib_inner_rho(self, z):
        return self.rho_sphere(z, self.R - self.rib_d)


# ---------------------------------------------------------------------------
# 2D / 3D helpers
# ---------------------------------------------------------------------------

def nseg(r, chord=0.5):
    return int(max(24, min(1440, 2 * math.pi * r / chord)))


def circle(r, cx=0.0, cy=0.0, chord=0.5):
    return CrossSection.circle(r, nseg(r, chord)).translate([cx, cy])


def rect(x0, y0, x1, y1):
    return CrossSection([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])


def poly(pts):
    pts = list(pts)
    a = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return CrossSection([pts[::-1] if a < 0 else pts])


def rrect(x0, y0, x1, y1, r):
    return rect(x0 + r, y0 + r, x1 - r, y1 - r).offset(r, JoinType.Round, 2.0, 48)


def slot2d(x0, y0, x1, y1, w):
    c = CrossSection.circle(w / 2, 32)
    return CrossSection.batch_hull([c.translate([x0, y0]), c.translate([x1, y1])])


def bar2d(x0, y0, x1, y1, w):
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L * w / 2, dx / L * w / 2
    return poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])


def ext(cs, z0, z1):
    cs = cs.simplify(0.002)          # drop near-duplicate vertices, slicers like clean meshes
    return cs.extrude(z1 - z0).translate([0, 0, z0])


def union(items):
    items = [i for i in items if i is not None]
    if isinstance(items[0], CrossSection):
        return CrossSection.batch_boolean(items, OpType.Add)
    return Manifold.batch_boolean(items, OpType.Add)


def prism_yz(prof: CrossSection, x0, x1):
    """extrude a (y, z) profile along x"""
    m = prof.extrude(x1 - x0)
    return m.transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]])


# ---------------------------------------------------------------------------
# frame
# ---------------------------------------------------------------------------

def frame(p: P):
    base, holes, feats = [], [], []
    base.append(rrect(p.hub_x0, -p.hub_hw, p.hub_x1, p.hub_hw, 6.0))
    base.append(rrect(10.0, -p.nose_hw, p.nose_x1, p.nose_hw, 3.0))
    rs = p.r_screw
    for (mx, my, a) in p.motor_xy():
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        base.append(bar2d(ca * 12, sa * 12, mx, my, p.arm_w))
        base.append(circle(p.motor_pad_d / 2, mx, my))
        base.append(bar2d(mx, my, ca * (rs + 3.5), sa * (rs + 3.5), p.ext_w))
        base.append(rrect(rs - p.tab_in, -p.tip_w / 2, rs + 3.5, p.tip_w / 2, 2.0).rotate(a))
        holes.append(circle(p.clamp_hole_d / 2, ca * rs, sa * rs))
        for k in range(p.motor_holes):
            t = math.radians(a + p.motor_hole_rot + k * 360.0 / p.motor_holes)
            holes.append(circle(p.motor_hole_d / 2, mx + p.motor_hole_circle / 2 * math.cos(t),
                                my + p.motor_hole_circle / 2 * math.sin(t), chord=0.2))
        holes.append(circle(p.motor_center_hole / 2, mx, my, chord=0.3))
        # U channel for the motor lead
        r0, r1 = 23.5, p.r_motor - p.motor_bell_d / 2 - 0.6
        for s in (-1, 1):
            off = s * (p.arm_w / 2 - p.arm_wall_t / 2 - 0.05)
            ox, oy = -sa * off, ca * off
            w = bar2d(ca * r0 + ox, sa * r0 + oy, ca * r1 + ox, sa * r1 + oy, p.arm_wall_t)
            feats.append(ext(w, 0, p.arm_wall_h))
        # stiffening rib on the arm extension
        r0 = p.r_motor + p.motor_bell_d / 2 + 0.6
        r1 = rs - p.tab_in - 0.4
        feats.append(ext(bar2d(ca * r0, sa * r0, ca * r1, sa * r1, p.ext_rib_t), 0, p.ext_rib_h))

    holes.append(rrect(-10.5, -8.0, 6.5, 8.0, 4.0))
    holes.append(rrect(-17.5, -6.0, -12.5, 6.0, 2.0))
    holes.append(rrect(-9.0, 9.6, 8.0, 14.6, 2.0))
    holes.append(rrect(-9.0, -14.6, 8.0, -9.6, 2.0))
    yb = p.batt_n * p.batt_w / 2 + 1.0 + p.strap_slot_w / 2
    for s in (-1, 1):
        holes.append(rrect(p.batt_x - p.strap_slot_l / 2, s * yb - p.strap_slot_w / 2,
                           p.batt_x + p.strap_slot_l / 2, s * yb + p.strap_slot_w / 2, 0.9))
    h = p.fc_spacing / 2
    fc_pts = [(sx * h, sy * h) for sx in (-1, 1) for sy in (-1, 1)]
    for (x, y) in fc_pts:
        holes.append(circle(p.fc_pilot_d / 2, x, y, chord=0.15))
    holes.append(rrect(17.0, -4.5, 22.0, 4.5, 1.5))

    parts = [ext(union(base) - union(holes), -p.t_plate, 0.0)]
    for (x, y) in fc_pts:
        parts.append(ext(circle(p.fc_post_d / 2, x, y) - circle(p.fc_pilot_d / 2, x, y, chord=0.15), 0, p.fc_post_h))

    # camera cradle: two cheeks with a slotted pivot, plus small gussets kept below the props
    prof = CrossSection.batch_hull([rect(16.5, 0.0, 23.0, 2.0), circle(3.2, p.cam_x, p.cam_z)])
    prof = prof - slot2d(p.cam_x, p.cam_z - p.cam_hole_slot / 2, p.cam_x, p.cam_z + p.cam_hole_slot / 2, p.cam_hole_d)
    y_in = p.cam_w / 2 + p.cam_gap
    cheek = prof.extrude(p.cam_plate_t).rotate([90, 0, 0])
    gusset = prism_yz(poly([(0.0, 0.0), (2.4, 0.0), (0.0, 6.0)]), 17.0, 22.5)
    parts.append(cheek.translate([0, y_in + p.cam_plate_t, 0]))
    parts.append(cheek.translate([0, -y_in, 0]))
    parts.append(gusset.translate([0, y_in + p.cam_plate_t, 0]))
    parts.append(gusset.mirror([0, 1, 0]).translate([0, -(y_in + p.cam_plate_t), 0]))
    return union(parts + feats)


def vtx_deck(p: P):
    """sits on the FC, held by the same four screws"""
    h = p.fc_spacing / 2
    z_fc_top = p.fc_post_h + p.fc_board_t
    z0 = z_fc_top + p.deck_foot_h
    outline = union([rrect(-16.0, -9.2, p.deck_front_x, 9.2, 3.0),
                     rrect(-16.0, -16.0, 16.0, -9.0, 3.0),
                     rrect(-16.0, 9.0, 16.0, 16.0, 3.0)])
    holes = [circle(p.fc_clear_d / 2, sx * h, sy * h, chord=0.15) for sx in (-1, 1) for sy in (-1, 1)]
    holes += [rrect(-11.0, -6.0, 6.0, 6.0, 3.0),
              rrect(-9.0, 10.5, 9.5, 14.0, 1.5), rrect(-9.0, -14.0, 9.5, -10.5, 1.5),
              rrect(-15.0, -4.0, -13.2, -1.0, 0.6), rrect(-15.0, 1.0, -13.2, 4.0, 0.6)]   # last two: antenna zip tie
    parts = [ext(outline - union(holes), z0, z0 + p.deck_t)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(ext(circle(p.deck_foot_d / 2, sx * h, sy * h) - circle(p.fc_clear_d / 2, sx * h, sy * h, 0.15),
                             z_fc_top, z0))
    return union(parts)


# ---------------------------------------------------------------------------
# cage
# ---------------------------------------------------------------------------
# Ribs are drawn in their own plane: u = horizontal distance from the axis, v = z.
# All joint slots are horizontal, so every rib slides in sideways, towards the
# centre, and catches all of its rings at once.

def band_poly(Rin, Rout, zc, lat0, lat1, step=0.4):
    n = max(8, int(abs(lat1 - lat0) / step))
    a = np.radians(np.linspace(lat0, lat1, n))
    outer = [(Rout * math.cos(t), zc + Rout * math.sin(t)) for t in a]
    inner = [(Rin * math.cos(t), zc + Rin * math.sin(t)) for t in a[::-1]]
    return poly(outer + inner)


def split_A(p: P):
    """half-lap split radius on ring A"""
    return p.rhoA - p.ringA_d / 2.0


def split_notch(p: P, z):
    """rings B and D: the rib only loses a small notch on its inner edge"""
    return p.rib_inner_rho(z) + p.notch


def rib_upper_2d(p: P, long=True):
    Rin, Rout = p.R - p.rib_d, p.R
    if long:
        lat_hi = math.degrees(math.acos(p.pole_r_end / Rout))
    else:
        zt = p.zB + p.ringB_t / 2 + p.fit + 3.0       # stop 3 mm above ring B
        lat_hi = math.degrees(math.asin((zt - p.zc) / Rin))
    cs = band_poly(Rin, Rout, p.zc, -30.0, lat_hi) ^ rect(-1, -0.7, 200, 200)
    c = p.fit
    cs = cs - rect(-5, p.zA_top - p.ringA_t / 2 - c, split_A(p), p.zA_top + p.ringA_t / 2 + c)
    cs = cs - rect(-5, p.zB - p.ringB_t / 2 - c, split_notch(p, p.zB) + 0.15, p.zB + p.ringB_t / 2 + c)
    return cs


def rib_lower_2d(p: P):
    Rin, Rout = p.R - p.rib_d, p.R
    cs = band_poly(Rin, Rout, p.zc, p.ringD_lat - 15.0, 10.0)
    cs = cs ^ rect(-1, -300, 200, -1.3)
    cs = cs ^ rect(-1, p.zD - p.ringD_t / 2, 200, 200)     # flush with ring D, flat landing
    c = p.fit
    cs = cs - rect(-5, p.zA_bot - p.ringA_t / 2 - c, split_A(p), p.zA_bot + p.ringA_t / 2 + c)
    cs = cs - rect(-5, p.zD - p.ringD_t / 2 - c, split_notch(p, p.zD) + 0.15, p.zD + p.ringD_t / 2 + c)
    return cs


def place_rib(p: P, cs2d: CrossSection, az):
    m = cs2d.extrude(p.rib_t).translate([0, 0, -p.rib_t / 2])
    return m.rotate([90, 0, 0]).rotate([0, 0, az])


def ring_slots(p: P, rs):
    c = p.fit
    return union([rect(rs, -(p.rib_t / 2 + c), rs + 30, p.rib_t / 2 + c).rotate(az) for az in p.rib_az])


def ring_A_2d(p: P):
    ro = p.rhoA
    ri = ro - p.ringA_d
    tabs, holes = [], []
    for (_, _, a) in p.motor_xy():
        tabs.append(rrect(p.r_screw - p.tab_in, -p.tip_w / 2, ri + 1.0, p.tip_w / 2, 2.0).rotate(a))
        holes.append(circle(p.clamp_hole_d / 2, math.cos(math.radians(a)) * p.r_screw,
                            math.sin(math.radians(a)) * p.r_screw, chord=0.2))
    cs = union([circle(ro) - circle(ri)] + tabs) - union(holes)
    return cs - ring_slots(p, split_A(p))


def ring_notched_2d(p: P, z, w_in, w_out):
    rs = split_notch(p, z)
    return (circle(rs + w_out) - circle(rs - w_in)) - ring_slots(p, rs)


def pole_cap(p: P):
    """small disc with blind slots, rests on the tips of the four long ribs"""
    z0 = p.zc + math.sqrt(p.R ** 2 - p.pole_r_end ** 2) - p.cap_slot_h
    disc = ext(circle(p.cap_r) - circle(1.6), z0, z0 + p.cap_t)
    c = p.fit
    cuts = [ext(rect(p.pole_r_end - 0.6, -(p.rib_t / 2 + c), p.cap_r + 2, p.rib_t / 2 + c).rotate(az), z0 - 1, z0 + p.cap_slot_h)
            for az in p.long_rib_az]
    return disc - union(cuts)


def cage_2d(p: P):
    return {
        'ring_a': (ring_A_2d(p), p.ringA_t),
        'ring_b': (ring_notched_2d(p, p.zB, p.ringB_in, p.ringB_out), p.ringB_t),
        'ring_d': (ring_notched_2d(p, p.zD, p.ringD_in, p.ringD_out), p.ringD_t),
        'rib_upper_long': (rib_upper_2d(p, True), p.rib_t),
        'rib_upper_short': (rib_upper_2d(p, False), p.rib_t),
        'rib_lower': (rib_lower_2d(p), p.rib_t),
    }


# ---------------------------------------------------------------------------
# assembly and print orientation
# ---------------------------------------------------------------------------

UPPER = ('ring_a_top', 'ring_b', 'ribs_upper', 'pole_cap')
LOWER = ('ring_a_bottom', 'ring_d', 'ribs_lower')


def assembly(p: P):
    c = cage_2d(p)
    out = {'frame': frame(p), 'vtx_deck': vtx_deck(p)}
    out['ring_a_top'] = ext(c['ring_a'][0], p.zA_top - p.ringA_t / 2, p.zA_top + p.ringA_t / 2)
    out['ring_a_bottom'] = ext(c['ring_a'][0], p.zA_bot - p.ringA_t / 2, p.zA_bot + p.ringA_t / 2)
    out['ring_b'] = ext(c['ring_b'][0], p.zB - p.ringB_t / 2, p.zB + p.ringB_t / 2)
    out['ring_d'] = ext(c['ring_d'][0], p.zD - p.ringD_t / 2, p.zD + p.ringD_t / 2)
    out['ribs_upper'] = union([place_rib(p, c['rib_upper_long' if az in p.long_rib_az else 'rib_upper_short'][0], az)
                               for az in p.rib_az])
    out['ribs_lower'] = union([place_rib(p, c['rib_lower'][0], az) for az in p.rib_az])
    out['pole_cap'] = pole_cap(p)
    return out


PRINT_COUNTS = {'frame': 1, 'vtx_deck': 1, 'ring_a': 2, 'ring_b': 1, 'ring_d': 1,
                'rib_upper_long': 4, 'rib_upper_short': 4, 'rib_lower': 8, 'pole_cap': 1}


def print_parts(p: P):
    """every part flat on z = 0, ready to slice"""
    pr = {'frame': frame(p)}
    pr['vtx_deck'] = vtx_deck(p).mirror([0, 0, 1])
    pr['pole_cap'] = pole_cap(p).mirror([0, 0, 1])              # slots facing up
    for k, (cs, t) in cage_2d(p).items():
        pr[k] = cs.extrude(t)
    for k, m in pr.items():
        pr[k] = m.translate([0, 0, -m.bounding_box()[2]])
    return pr


# ---------------------------------------------------------------------------
# stand-in hardware for the checks
# ---------------------------------------------------------------------------

def camera_solid(p: P, tilt):
    body = Manifold.cube([p.cam_depth, p.cam_w, p.cam_w]).translate([-p.cam_depth / 2, -p.cam_w / 2, -p.cam_w / 2])
    lens = Manifold.cylinder(p.cam_lens_len, p.cam_lens_d / 2, -1, 32).rotate([0, 90, 0]).translate([p.cam_depth / 2, 0, 0])
    return (body + lens).rotate([0, -tilt, 0]).translate([p.cam_x, 0, p.cam_z])


def stand_in_hardware(p: P, tilt=None):
    tilt = p.cam_tilt_default if tilt is None else tilt
    hw = {}
    hw['motors'] = union([Manifold.cylinder(p.motor_bell_h, p.motor_bell_d / 2, -1, 48).translate([x, y, 0])
                          for (x, y, _) in p.motor_xy()])
    hw['props'] = union([Manifold.cylinder(p.prop_z1 - p.prop_z0, p.prop_d / 2, -1, 96).translate([x, y, p.prop_z0])
                         for (x, y, _) in p.motor_xy()])
    b = p.fc_board / 2
    hw['fc'] = (Manifold.cube([p.fc_board, p.fc_board, p.fc_board_t]).translate([-b, -b, p.fc_post_h]) +
                Manifold.cube([22.0, 22.0, p.fc_comp_h]).translate([-11.0, -11.0, p.fc_post_h + p.fc_board_t]))
    hw['camera'] = camera_solid(p, tilt)
    z_deck = p.fc_post_h + p.fc_board_t + p.deck_foot_h + p.deck_t
    hw['vtx'] = Manifold.cube([18.0, 14.0, 4.0]).translate([-10.0, -7.0, z_deck])
    W = p.batt_n * p.batt_w
    hw['batteries'] = Manifold.cube([p.batt_l, W, p.batt_t]).translate(
        [p.batt_x - p.batt_l / 2, -W / 2, -p.t_plate - p.batt_t - 0.3])
    return hw


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def mesh_pts(m: Manifold):
    return np.asarray(m.to_mesh().vert_properties)[:, :3]


def fib_dirs(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)


def wall_margins(asm, hw, ndir=6000):
    """Push an infinite flat wall in from every direction until it touches the
    cage. Report how far it still is from each part, worst direction."""
    C = np.concatenate([mesh_pts(asm[k]) for k in UPPER + LOWER])
    D = fib_dirs(ndir)
    hC = (C @ D.T).max(0)
    res = {}
    for k, m in hw.items():
        marg = hC - (mesh_pts(m) @ D.T).max(0)
        i = int(np.argmin(marg))
        res[k] = (float(marg[i]), D[i].round(3).tolist())
    return res


def interferences(asm, hw):
    out = {}
    names = list(asm)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            v = (asm[names[i]] ^ asm[names[j]]).volume()
            if v > 1e-3:
                out[f'{names[i]} x {names[j]}'] = round(v, 3)
    for k, m in hw.items():
        for n, a in asm.items():
            v = (m ^ a).volume()
            if v > 1e-3:
                out[f'{k} x {n}'] = round(v, 3)
    return out


def camera_sweep(p: P, asm, hw):
    others = {'frame': asm['frame'], 'vtx_deck': asm['vtx_deck'], 'fc': hw['fc'], 'vtx': hw['vtx'], 'props': hw['props']}
    hits = {}
    for tilt in range(0, 41, 5):
        cam = camera_solid(p, tilt)
        h = [k for k, m in others.items() if (cam ^ m).volume() > 1e-3]
        if h:
            hits[tilt] = h
    return hits


def assembly_paths(p: P, asm):
    """ribs must slide in horizontally, domes must lift off with the props on"""
    c = cage_2d(p)
    up_rings = asm['ring_a_top'] + asm['ring_b']
    lo_rings = asm['ring_a_bottom'] + asm['ring_d']
    worst = 0.0
    for az in p.rib_az:
        for cs, rings in ((c['rib_upper_long' if az in p.long_rib_az else 'rib_upper_short'][0], up_rings),
                          (c['rib_lower'][0], lo_rings)):
            r = place_rib(p, cs, az)
            ca, sa = math.cos(math.radians(az)), math.sin(math.radians(az))
            for d in (0.0, 0.3, 1.0, 2.0, 4.0, 8.0):
                worst = max(worst, (r.translate([ca * d, sa * d, 0]) ^ rings).volume())
    up = union([asm[k] for k in UPPER])
    lo = union([asm[k] for k in LOWER])
    hw = stand_in_hardware(p)
    core = union([asm['frame'], asm['vtx_deck'], hw['motors'], hw['props'], hw['camera'], hw['vtx'], hw['batteries']])
    steps = (0.5, 2, 5, 10, 16, 25, 40)
    return {
        'rib slide-in collision (mm3)': round(worst, 4),
        'upper dome lift-off collision (mm3)': round(max((up.translate([0, 0, d]) ^ core).volume() for d in steps), 4),
        'lower dome drop-off collision (mm3)': round(max((lo.translate([0, 0, -d]) ^ core).volume() for d in steps), 4),
        'static gap props-cage (mm)': round(hw['props'].min_gap(up + lo, 30.0), 2),
        'static gap props-frame (mm)': round(hw['props'].min_gap(asm['frame'], 30.0), 2),
    }


def centroid(m: Manifold):
    mesh = m.to_mesh()
    V = np.asarray(mesh.vert_properties)[:, :3]
    F = np.asarray(mesh.tri_verts)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = np.einsum('ij,ij->i', a, np.cross(b, c)) / 6.0
    return (((a + b + c) / 4.0) * vol[:, None]).sum(0) / vol.sum()


def mass_budget(p: P, asm):
    rho = p.density / 1000.0
    printed = {k: m.volume() * rho for k, m in asm.items()}
    other = {
        'stock electronics (55 g minus 24.2 g stock frame)': (30.8, [1.5, 0, 5.0]),
        'batteries 2x BT2.0 450 1S': (25.4, [p.batt_x, 0, -p.t_plate - p.batt_t / 2 - 0.3]),
        'screws, nuts, strap': (1.6, [0, 0, -2.0]),
    }
    tot = sum(printed.values()) + sum(v[0] for v in other.values())
    mom = sum(printed[k] * centroid(asm[k]) for k in asm) + sum(m * np.array(c) for m, c in other.values())
    return printed, other, tot, mom / tot


def joint_report(p: P):
    rep = {'ring A half-lap, rib keeps (mm)': p.rhoA - split_A(p),
           'ring A half-lap, ring keeps (mm)': split_A(p) - (p.rhoA - p.ringA_d)}
    for nm, z, t in (('B', p.zB, p.ringB_t), ('D', p.zD, p.ringD_t)):
        rs = split_notch(p, z)
        worst = 1e9
        for zz in np.linspace(z - t / 2 - p.fit, z + t / 2 + p.fit, 9):
            lat = math.asin(max(-1, min(1, (zz - p.zc) / p.R)))
            worst = min(worst, (p.rho_sphere(zz) - max(rs + 0.15, p.rib_inner_rho(zz))) * math.cos(lat))
        rep[f'ring {nm} notch, rib keeps (mm of {p.rib_d})'] = worst
    return rep


def to_trimesh(m: Manifold):
    import trimesh
    mesh = m.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def report(p: P):
    asm = assembly(p)
    hw = stand_in_hardware(p)
    lines = []
    lines.append('wall test (flat wall from 6000 directions, distance left):')
    for k, v in wall_margins(asm, hw).items():
        lines.append(f'  {k:10s} {v[0]:6.1f} mm')
    lines.append(f'overlaps between parts: {interferences(asm, hw) or "none"}')
    lines.append(f'camera 0-40 deg collisions: {camera_sweep(p, asm, hw) or "none"}')
    for k, v in assembly_paths(p, asm).items():
        lines.append(f'{k}: {v}')
    for k, v in joint_report(p).items():
        lines.append(f'{k}: {v:.2f}')
    printed, other, tot, cg = mass_budget(p, asm)
    lines.append('mass:')
    for k, v in printed.items():
        lines.append(f'  {k:16s} {v:5.1f} g')
    lines.append(f'  printed total    {sum(printed.values()):5.1f} g')
    for k, (m, _) in other.items():
        lines.append(f'  {k}: {m:.1f} g')
    lines.append(f'all-up weight (estimate): {tot:.1f} g')
    lines.append(f'CG z = {cg[2]:.1f} mm, ball centre z = {p.zc} mm -> CG {p.zc - cg[2]:.1f} mm below centre')
    return '\n'.join(lines)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Cetus X ORB checks')
    ap.add_argument('--motor-holes', type=int, default=4)
    a = ap.parse_args()
    print(report(P(motor_holes=a.motor_holes)))
