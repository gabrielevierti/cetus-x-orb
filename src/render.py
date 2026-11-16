#!/usr/bin/env python3
"""Renders for the README. Small software z-buffer, no GPU needed.

    python3 src/render.py            # everything into docs/img/
    python3 src/render.py hero fpv   # only some of them
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from manifold3d import CrossSection, Manifold, OpType

from orb import P, UPPER, LOWER, assembly, camera_solid, union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'img')

WHITE = (238, 236, 230)
ORANGE = (240, 106, 34)
COL = {
    'cage': WHITE, 'frame': ORANGE, 'deck': ORANGE,
    'motor_base': (44, 46, 52), 'motor_bell': (62, 66, 74), 'motor_cap': (150, 154, 160),
    'prop': (38, 118, 214), 'fc': (22, 96, 58), 'chip': (24, 24, 26), 'plug': (236, 236, 228),
    'usb': (175, 178, 184), 'cam': (26, 26, 28), 'glass': (40, 60, 95), 'vtx': (132, 32, 34),
    'shield': (190, 192, 198), 'antenna': (22, 22, 24), 'batt': (40, 42, 46), 'label': (246, 196, 40),
    'strap': (18, 18, 20), 'screw': (186, 188, 194),
}


# ---------------------------------------------------------------------------
# render-only hardware, a bit nicer than the boxes used by the checks
# ---------------------------------------------------------------------------

def box(x0, y0, z0, x1, y1, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def cyl(r, z0, z1, x=0.0, y=0.0, n=48):
    return Manifold.cylinder(z1 - z0, r, -1, n).translate([x, y, z0])


def blade(r0, r1, pitch):
    pts = [(r0, -3.0), (r0 + 6, -3.8), (r1 * 0.75, -3.2), (r1 - 1.0, -1.8), (r1, -0.2), (r1, 1.0),
           (r1 - 1.5, 2.0), (r1 * 0.6, 2.4), (r0, 2.0)]
    m = CrossSection([pts]).extrude(0.9).translate([0, 0, -0.45])
    return m.rotate([pitch, 0, 0])


def hardware(p: P, tilt=None):
    tilt = p.cam_tilt_default if tilt is None else tilt
    hw = []
    for i, (mx, my, a) in enumerate(p.motor_xy()):
        hw.append(('motor_base', cyl(6.6, 0, 2.2, mx, my)))
        hw.append(('motor_bell', cyl(7.1, 2.2, 9.6, mx, my)))
        hw.append(('motor_cap', cyl(6.2, 9.6, 10.5, mx, my)))
        hw.append(('motor_cap', cyl(0.75, 10.5, 14.0, mx, my, 16)))
        hub = cyl(3.0, 10.5, 14.5, mx, my, 32)
        cw = 1 if i % 2 == 0 else -1
        bl = [blade(2.0, p.prop_d / 2, 14 * cw).rotate([0, 0, k * 90 + 25 + 20 * i]) for k in range(4)]
        if cw < 0:
            bl = [b.mirror([0, 1, 0]) for b in bl]
        hw.append(('prop', union([hub] + [b.translate([mx, my, 12.4]) for b in bl])))
    zb = p.fc_post_h
    b = p.fc_board / 2
    hw.append(('fc', box(-b, -b, zb, b, b, zb + p.fc_board_t)))
    zt = zb + p.fc_board_t
    hw.append(('chip', box(-4, -4, zt, 4, 4, zt + 1.0)))
    hw.append(('chip', box(-9, 6, zt, -5, 10, zt + 0.9)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            hw.append(('chip', box(sx * 9 - 2.5, sy * 4 - 2.5, zt, sx * 9 + 2.5, sy * 4 + 2.5, zt + 1.1)))
            hw.append(('plug', box(sx * 11 - 2, sy * 14.5 - 1.5, zt, sx * 11 + 2, sy * 14.5 + 1.5, zt + 2.2)))
    hw.append(('usb', box(-16.5, -4.0, zt, -12.5, 4.0, zt + 2.0)))
    # camera
    t = math.radians(tilt)
    cam = box(-p.cam_depth / 2, -p.cam_w / 2, -p.cam_w / 2, p.cam_depth / 2, p.cam_w / 2, p.cam_w / 2)
    barrel = Manifold.cylinder(p.cam_lens_len, p.cam_lens_d / 2, 4.0, 40).rotate([0, 90, 0]).translate([p.cam_depth / 2, 0, 0])
    glass = Manifold.cylinder(0.6, 3.0, -1, 40).rotate([0, 90, 0]).translate([p.cam_depth / 2 + p.cam_lens_len, 0, 0])
    for k, m in (('cam', cam + barrel), ('glass', glass)):
        hw.append((k, m.rotate([0, -tilt, 0]).translate([p.cam_x, 0, p.cam_z])))
    # vtx and antenna
    zd = p.fc_post_h + p.fc_board_t + p.deck_foot_h + p.deck_t
    hw.append(('vtx', box(-10, -7, zd, 8, 7, zd + 1.0)))
    hw.append(('shield', box(-6, -5, zd + 1.0, 4, 5, zd + 2.6)))
    hw.append(('antenna', cyl(0.6, zd, zd + 34, -14.1, 0, 12)))
    hw.append(('antenna', cyl(1.6, zd + 22, zd + 38, -14.1, 0, 20)))
    # batteries, label, strap
    z1 = -p.t_plate - 0.3
    for s in (-1, 1):
        y0 = 0 if s > 0 else -p.batt_w
        hw.append(('batt', box(p.batt_x - p.batt_l / 2, y0 + 0.2, z1 - p.batt_t, p.batt_x + p.batt_l / 2, y0 + p.batt_w - 0.2, z1)))
        hw.append(('label', box(p.batt_x + 6, y0 + 0.05, z1 - p.batt_t - 0.12, p.batt_x + 24, y0 + p.batt_w - 0.05, z1 - 0.4)))
    yb = p.batt_n * p.batt_w / 2 + 1.0 + p.strap_slot_w / 2
    sx0, sx1 = p.batt_x - 4.8, p.batt_x + 4.8
    zb0 = z1 - p.batt_t - 0.9
    hw.append(('strap', box(sx0, -yb - 0.7, zb0, sx1, yb + 0.7, zb0 + 0.8)))
    for s in (-1, 1):
        hw.append(('strap', box(sx0, s * yb - 0.7, zb0, sx1, s * yb + 0.7, 1.0)))
    hw.append(('strap', box(sx0, -yb - 0.7, 0.2, sx1, yb + 0.7, 1.0)))
    # M2 screws and nuts on the four clamps
    for (_, _, a) in p.motor_xy():
        x, y = p.r_screw * math.cos(math.radians(a)), p.r_screw * math.sin(math.radians(a))
        hw.append(('screw', cyl(1.9, p.ringA_t, p.ringA_t + 1.4, x, y, 24)))
        hw.append(('screw', Manifold.cylinder(1.6, 2.3, -1, 6).translate([x, y, p.zA_bot - p.ringA_t / 2 - 1.6])))
    return hw


def scene(p: P, explode=0.0, cage=True, hw=True, tilt=None, frame_on=True):
    asm = assembly(p)
    items = []
    for k, m in asm.items():
        if k in UPPER:
            if cage:
                items.append(('cage', m.translate([0, 0, explode])))
        elif k in LOWER:
            if cage:
                items.append(('cage', m.translate([0, 0, -explode])))
        elif frame_on:
            items.append(('frame' if k == 'frame' else 'deck', m))
    if hw:
        items += hardware(p, tilt)
    out = []
    for k, m in items:
        mesh = m.to_mesh()
        out.append((np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts).astype(np.int64), COL[k]))
    return out


# ---------------------------------------------------------------------------
# rasterizer
# ---------------------------------------------------------------------------

def look_at(eye, target, up=(0, 0, 1)):
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    return np.stack([r, np.cross(r, f), f]), eye


def project(V, cam, W, H, proj, scale=None, fov=None):
    Rm, eye = cam
    Pc = (V - eye) @ Rm.T
    if proj == 'ortho':
        return W / 2 + Pc[:, 0] * scale, H / 2 - Pc[:, 1] * scale, Pc[:, 2]
    if proj == 'persp':
        f = (W / 2) / math.tan(math.radians(fov / 2))
        z = np.maximum(Pc[:, 2], 1e-3)
        return W / 2 + f * Pc[:, 0] / z, H / 2 - f * Pc[:, 1] / z, np.linalg.norm(Pc, axis=1)
    th = np.arctan2(np.hypot(Pc[:, 0], Pc[:, 1]), Pc[:, 2])       # equidistant fisheye
    ph = np.arctan2(Pc[:, 1], Pc[:, 0])
    f = (W / 2) / math.radians(fov / 2)
    d = np.linalg.norm(Pc, axis=1)
    d[th > math.radians(fov / 2 + 25)] = np.inf
    return W / 2 + f * th * np.cos(ph), H / 2 - f * th * np.sin(ph), d


def raster(meshes, cam, W, H, proj='persp', scale=None, fov=30, light=(-0.45, -0.55, 0.75), edges=True, ss=2, edge_k=0.42):
    W2, H2 = W * ss, H * ss
    sc = None if scale is None else scale * ss
    zbuf = np.full((H2, W2), np.inf)
    cbuf = np.zeros((H2, W2, 3))
    nbuf = np.zeros((H2, W2, 3))
    ibuf = np.full((H2, W2), -1, np.int32)
    L = np.asarray(light, float)
    L /= np.linalg.norm(L)
    Rm, eye = cam
    for mid, (V, F, rgb) in enumerate(meshes):
        sx, sy, dep = project(V, cam, W2, H2, proj, sc, fov)
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        n = np.cross(b - a, c - a)
        nl = np.linalg.norm(n, axis=1)
        ok = nl > 1e-12
        n[ok] /= nl[ok, None]
        cen = (a + b + c) / 3
        vdir = eye - cen if proj != 'ortho' else np.tile(-Rm[2], (len(F), 1))
        vdir /= np.linalg.norm(vdir, axis=1)[:, None]
        hvec = vdir + L
        hvec /= np.linalg.norm(hvec, axis=1)[:, None]
        lam = np.clip(n @ L, 0, 1)
        spec = np.clip(np.einsum('ij,ij->i', n, hvec), 0, 1) ** 24
        fill = np.clip(n @ np.array([0.6, 0.5, 0.2]), 0, 1)
        shade = 0.40 + 0.52 * lam + 0.12 * fill
        base = np.asarray(rgb, float) / 255.0
        cols = np.clip(base[None, :] * shade[:, None] + 0.18 * spec[:, None], 0, 1)
        X = np.stack([sx[F], sy[F], dep[F]], -1)
        for i in np.nonzero(ok)[0]:
            t = X[i]
            if not np.all(np.isfinite(t[:, 2])):
                continue
            x0, x1 = int(max(0, np.floor(t[:, 0].min()))), int(min(W2 - 1, np.ceil(t[:, 0].max())))
            y0, y1 = int(max(0, np.floor(t[:, 1].min()))), int(min(H2 - 1, np.ceil(t[:, 1].max())))
            if x1 < x0 or y1 < y0:
                continue
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1 - w0 - w1
            ins = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not ins.any():
                continue
            d = w0 * az + w1 * bz + w2 * cz
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            upd = ins & (d < sub)
            if not upd.any():
                continue
            sub[upd] = d[upd]
            cbuf[y0:y1 + 1, x0:x1 + 1][upd] = cols[i]
            nbuf[y0:y1 + 1, x0:x1 + 1][upd] = n[i]
            ibuf[y0:y1 + 1, x0:x1 + 1][upd] = mid
    if edges:
        zf = np.where(np.isfinite(zbuf), zbuf, 1e7)
        e = np.zeros((H2, W2), bool)
        for dy, dx in ((0, 1), (1, 0)):
            z2 = np.roll(zf, (-dy, -dx), (0, 1))
            e |= np.abs(z2 - zf) > 1.5 * (1 if proj != 'ortho' else 1)
            e |= (np.einsum('ijk,ijk->ij', np.roll(nbuf, (-dy, -dx), (0, 1)), nbuf) < 0.7) & np.isfinite(zbuf)
            e |= np.roll(ibuf, (-dy, -dx), (0, 1)) != ibuf
        cbuf[e] *= edge_k
    return cbuf, zbuf


def shadow_mask(meshes, cam, W, H, proj, scale, fov, ground_z, sun=(0.25, 0.15, -1.0), ss=2):
    S = np.asarray(sun, float)
    S /= np.linalg.norm(S)
    img = Image.new('L', (W * ss, H * ss), 0)
    dr = ImageDraw.Draw(img)
    for V, F, _ in meshes:
        t = (V[:, 2] - ground_z) / -S[2]
        G = V + t[:, None] * S
        G[:, 2] = ground_z
        sx, sy, _ = project(G, cam, W * ss, H * ss, proj, None if scale is None else scale * ss, fov)
        for f in F:
            dr.polygon([(sx[f[0]], sy[f[0]]), (sx[f[1]], sy[f[1]]), (sx[f[2]], sy[f[2]])], fill=255)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(9 * ss)), float) / 255.0


def compose(cbuf, zbuf, W, H, shadow=None, bg=((226, 230, 235), (250, 250, 247)), ss=2):
    H2, W2 = zbuf.shape
    top, bot = np.array(bg[0], float) / 255, np.array(bg[1], float) / 255
    g = np.linspace(0, 1, H2)[:, None, None]
    back = top * (1 - g) + bot * g
    back = np.broadcast_to(back, (H2, W2, 3)).copy()
    if shadow is not None:
        back *= (1 - 0.32 * shadow)[..., None]
    empty = ~np.isfinite(zbuf)
    out = np.where(empty[..., None], back, cbuf)
    im = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
    return im.resize((W, H), Image.LANCZOS)


def render(meshes, cam, W, H, proj='persp', scale=None, fov=30, ground_z=None, ss=2, edges=True, edge_k=0.42):
    c, z = raster(meshes, cam, W, H, proj, scale, fov, edges=edges, ss=ss, edge_k=edge_k)
    sh = None if ground_z is None else shadow_mask(meshes, cam, W, H, proj, scale, fov, ground_z, ss=ss)
    return compose(c, z, W, H, sh, ss=ss)


def orbit(az, el, dist, target=(0, 0, 16)):
    a, e = math.radians(az), math.radians(el)
    d = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    return look_at(np.asarray(target) + d * dist, target)


def autocrop(im, pad=40):
    """trim the empty gradient around the subject"""
    a = np.asarray(im.convert('RGB'), float)
    ref = a[:, :1, :]                       # background colour of each row
    mask = np.abs(a - ref).sum(-1) > 12
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return im
    return im.crop((max(0, xs.min() - pad), max(0, ys.min() - pad), min(im.width, xs.max() + pad), min(im.height, ys.max() + pad)))


def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    try:
        return ImageFont.truetype(f'/usr/share/fonts/truetype/dejavu/{name}', size)
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# the images
# ---------------------------------------------------------------------------

def ground(p):
    return p.zD - p.ringD_t / 2


def hero(p):
    ms = scene(p)
    im = render(ms, orbit(-38, 22, 560), 1600, 1000, fov=31, ground_z=ground(p))
    im.save(f'{OUT}/hero.png')


def save_gif(frames, path, ms):
    """one shared palette for all frames, so colours don't flicker"""
    w, h = frames[0].size
    sheet = Image.new('RGB', (w * 4, h))
    for i, k in enumerate(range(0, len(frames), max(1, len(frames) // 4))[:4]):
        sheet.paste(frames[k], (i * w, 0))
    pal = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=ms, loop=0, optimize=True)


def turntable(p, frames=36, size=560):
    ms = scene(p)
    imgs = [render(ms, orbit(-90 + k * 360 / frames, 18, 470), size, size, fov=30, ground_z=ground(p), edge_k=0.62)
            for k in range(frames)]
    save_gif(imgs, f'{OUT}/turntable.gif', 90)


def exploded(p, frames=28, size=600):
    still = render(scene(p, explode=72), orbit(-38, 18, 800, (0, 0, 10)), 1200, 1400, fov=30)
    autocrop(still).save(f'{OUT}/exploded.png')
    imgs = []
    for k in range(frames):
        s = 0.5 - 0.5 * math.cos(2 * math.pi * k / frames)
        imgs.append(render(scene(p, explode=70 * s), orbit(-38 + 25 * s, 16, 690, (0, 0, 12)), size, size, fov=30,
                           edge_k=0.62))
    save_gif(imgs, f'{OUT}/exploded.gif', 110)


def frame_closeup(p):
    ms = scene(p, cage=False)
    im = render(ms, orbit(-145, 30, 350, (0, 0, 4)), 1400, 900, fov=30, ground_z=-p.t_plate - p.batt_t - 1.5)
    im.save(f'{OUT}/frame_electronics.png')
    ms = scene(p, cage=False, hw=False)
    im = render(ms, orbit(-55, 38, 360, (0, 0, 2)), 1400, 900, fov=30, ground_z=-p.t_plate)
    im.save(f'{OUT}/frame_printed.png')


def bottom(p):
    ms = scene(p)
    im = render(ms, orbit(-150, -38, 600, (0, 0, 0)), 1200, 900, fov=30)
    im.save(f'{OUT}/bottom_battery_access.png')


def fpv(p, tilt=25):
    import trimesh
    ms = []
    for V, F, c in scene(p, tilt=tilt):
        if c in (COL['cam'], COL['glass']):
            continue
        v, f = trimesh.remesh.subdivide_to_size(V, F, max_edge=4.0, max_iter=12)
        ms.append((v, f, c))
    t = math.radians(tilt)
    fwd = np.array([math.cos(t), 0, math.sin(t)])
    lens = np.array([p.cam_x, 0, p.cam_z]) + fwd * (p.cam_depth / 2 + p.cam_lens_len + 0.8)
    cam = look_at(lens, lens + fwd, up=(-math.sin(t), 0, math.cos(t)))
    W, H, fov = 960, 720, 128
    c, z = raster(ms, cam, W, H, 'fisheye', fov=fov, ss=2)
    H2, W2 = z.shape
    f = (W2 / 2) / math.radians(fov / 2)
    yy, xx = np.mgrid[0:H2, 0:W2]
    dx, dy = (xx + 0.5 - W2 / 2) / f, -(yy + 0.5 - H2 / 2) / f
    th, ph = np.hypot(dx, dy), np.arctan2(dy, dx)
    dw = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1) @ cam[0]
    elev = dw[..., 2]
    sky = np.array([0.72, 0.82, 0.92]) * (1 - 0.35 * elev[..., None].clip(0, 1)) + 0.12
    floor = np.array([0.62, 0.58, 0.52]) * (0.85 + 0.3 * (-elev[..., None]).clip(0, 1))
    back = np.where(elev[..., None] > 0, sky, floor)
    empty = ~np.isfinite(z)
    img = np.where(empty[..., None], back, c)
    vign = np.clip(1.15 - 0.45 * (th / math.radians(fov / 2)) ** 2, 0.5, 1)
    img = img * vign[..., None]
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    d = ImageDraw.Draw(im)
    d.text((24, 20), f'simulated FPV view, camera tilt {tilt}°', fill=(255, 255, 255), font=font(20))
    im.save(f'{OUT}/fpv_view.png')


def dimensions(p):
    """front view with the main sizes"""
    ms = scene(p)
    W, H, s = 1200, 1000, 4.4
    cam = look_at((900, 0, 20), (0, 0, 20))
    c, z = raster(ms, cam, W, H, 'ortho', scale=s, ss=2)
    im = compose(c, z, W, H, bg=((252, 252, 250), (252, 252, 250)))
    d = ImageDraw.Draw(im)
    ink = (60, 60, 64)

    def X(y):
        return W / 2 + (-y) * s       # looking down -x: screen right is -y

    def Y(zz):
        return H / 2 - (zz - 20) * s
    R = p.R
    top, bot = p.zc + R, p.zD - p.ringD_t / 2
    # width
    yl = Y(bot) + 40
    d.line([(X(R), yl), (X(-R), yl)], fill=ink, width=2)
    for xx in (X(R), X(-R)):
        d.line([(xx, yl - 10), (xx, yl + 10)], fill=ink, width=2)
        d.line([(xx, Y(p.zc)), (xx, yl + 10)], fill=(170, 170, 175), width=1)
    d.text(((X(R) + X(-R)) / 2 - 40, yl + 10), f'Ø {2 * R:.0f} mm', fill=ink, font=font(24))
    # height
    xr = X(-R) + 50
    d.line([(xr, Y(top)), (xr, Y(bot))], fill=ink, width=2)
    for yy in (Y(top), Y(bot)):
        d.line([(xr - 10, yy), (xr + 10, yy)], fill=ink, width=2)
        d.line([(X(0), yy), (xr + 10, yy)], fill=(170, 170, 175), width=1)
    d.text((xr + 14, (Y(top) + Y(bot)) / 2 - 12), f'{top - bot:.0f} mm', fill=ink, font=font(24))
    d.text((30, 26), 'front view, sitting on the landing ring', fill=(120, 120, 125), font=font(20))
    im.save(f'{OUT}/dimensions.png')


def plates(p):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MPoly, Rectangle
    from build import plates as layout_plates, footprint, BED
    layout, _, _ = layout_plates(p)
    fig, axs = plt.subplots(1, len(layout), figsize=(5.0 * len(layout), 5.4))
    for ax, (k, items) in zip(axs, layout.items()):
        ax.add_patch(Rectangle((0, 0), BED, BED, fc='#2b2b2e', ec='#111'))
        for name, m in items:
            fp = footprint(m)
            for g in ([fp] if fp.geom_type == 'Polygon' else list(fp.geoms)):
                col = '#f06a22' if any(s in name for s in ('frame', 'deck', 'fit')) else '#eeece6'
                ax.add_patch(MPoly(np.asarray(g.exterior.coords), fc=col, ec='#666', lw=0.4))
                for hole in g.interiors:
                    ax.add_patch(MPoly(np.asarray(hole.coords), fc='#2b2b2e', ec='#666', lw=0.4))
        ax.set_xlim(-4, BED + 4); ax.set_ylim(-4, BED + 4); ax.set_aspect('equal'); ax.axis('off')
        ax.set_title(k.split('_', 1)[0] + ': ' + k.split('_', 1)[1].replace('_', ' '), fontsize=11)
    fig.tight_layout()
    fig.savefig(f'{OUT}/plates.png', dpi=100, facecolor='#ffffff')


ALL = {'hero': hero, 'turntable': turntable, 'exploded': exploded, 'frame': frame_closeup,
       'bottom': bottom, 'fpv': fpv, 'dimensions': dimensions, 'plates': plates}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    p = P()
    for k in (sys.argv[1:] or ALL):
        print(k, flush=True)
        ALL[k](p)
