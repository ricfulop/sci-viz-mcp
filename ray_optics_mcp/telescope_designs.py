"""
Parametric telescope design builders for the ray_optics MCP server.

Every builder returns (objs, info): the ray-optics scene objects and a dict of
derived design quantities (focus positions, conic constants, magnification...).

Conventions
-----------
- Scene coordinates: x to the right, y DOWN. Light enters traveling +x.
- Mirror surfaces are ParamMirror conics parametrized as x = xv - s(t),
  s(t) = t^2 / (R + sign(R)*sqrt(R^2 - (1+K)t^2)), with R > 0 meaning the
  surface sags toward -x away from its vertex (both a primary facing the
  incoming beam and a Cassegrain convex secondary have R > 0 here).
- Refractive surfaces use the standard optics sign convention (R > 0 when the
  center of curvature is to the +x side of the vertex).
- Design formulas: classical two-mirror conics are exact confocal conics;
  Ritchey-Chretien uses the third-order aplanatic solution
  (K1 = -1 - 2B/(D M^3), K2 = -1 - 2[M(2M-1)+B/D]/(M-1)^3); Dall-Kirkham uses
  K2 = 0, K1 = -1 + k(M-1)(M+1)^2/M^3 with k the marginal-ray height ratio.
- Catadioptric presets (Schmidt-Cassegrain, Maksutov) are laid out paraxially
  and then the corrector strength / meniscus radius is auto-tuned by tracing
  the actual scene through the engine and minimizing the RMS spot radius.
"""

import math

from engine import run_scene

# Cauchy coefficients (A, B[um^2]) fitted to n_d and Abbe V_d
GLASS = {
    "BK7":   (1.5046, 0.00420),   # n_d = 1.5168, V_d = 64.2
    "F2":    (1.5942, 0.00892),   # n_d = 1.6200, V_d = 36.4
    "FPL53": (1.4317, 0.00242),   # n_d = 1.4388, V_d = 94.9 (ED fluorite-like)
}

_WL_D, _WL_F, _WL_C = 0.5876, 0.4861, 0.6563  # um
RGB_WAVELENGTHS = [473, 540, 635]  # nm, for chromatic demos


def _n(glass, wl_um=0.540):
    A, B = GLASS[glass]
    return A + B / wl_um ** 2


def _abbe(glass):
    A, B = GLASS[glass]
    n_d = A + B / _WL_D ** 2
    return (n_d - 1) / (B / _WL_F ** 2 - B / _WL_C ** 2)


# ── Scene-object helpers ─────────────────────────────────────────────────────

def _num(x):
    """Format a number for the engine's equation parser, which does NOT
    understand scientific notation ('1e-06' silently misparses as Euler's e)."""
    s = format(float(x), ".20f").rstrip("0").rstrip(".")
    return s if s and s != "-" else "0"

def _beams(x_src, yc, r_out, r_in=0.0, brightness=0.5, tilt_deg=0.0,
           wavelengths=None):
    """Parallel beam(s) traveling +x (rotated by tilt_deg for field angle),
    with an optional central hole of radius r_in (obstruction shadow)."""
    a = math.radians(tilt_deg)
    ux, uy = -math.sin(a), math.cos(a)  # source segment direction

    def pt(s):
        return {"x": x_src + s * ux, "y": yc + s * uy}

    spans = [(-r_out, r_out)] if r_in <= 0 else \
            [(-r_out, -r_in), (r_in, r_out)]
    objs = []
    for wl in (wavelengths or [None]):
        for s0, s1 in spans:
            beam = {"type": "Beam", "p1": pt(s0), "p2": pt(s1),
                    "brightness": brightness / (len(wavelengths or [1]))}
            if wl is not None:
                beam["wavelength"] = wl
            objs.append(beam)
    return objs


def _conic_mirror(xv, yc, R, K, spans, n=100, extra=None):
    """Conic mirror(s): x = xv - s(t), one ParamMirror PER (t_lo, t_hi) span.

    Disjoint spans (e.g. an annular primary) must be separate scene objects:
    pieces inside one ParamMirror are required to form a continuous curve.
    Returns a list of objects.
    """
    sgn = "+" if R >= 0 else "-"
    out = []
    for t_lo, t_hi in spans:
        piece = {
            "eqnX": f"{_num(xv)}-(t)^2/({_num(R)}{sgn}sqrt({_num(R * R)}"
                    f"-({_num(1 + K)})*(t)^2))",
            "eqnY": f"{_num(yc)}+t",
            "tMin": t_lo, "tMax": t_hi,
            "tStep": max((t_hi - t_lo) / n, 1e-6),
        }
        obj = {"type": "ParamMirror", "pieces": [piece]}
        if extra:
            obj.update(extra)
        out.append(obj)
    return out


def _annular_spans(r_hole, r_out):
    if r_hole <= 0:
        return [(-r_out, r_out)]
    return [(-r_out, -r_hole), (r_hole, r_out)]


def _detector(cx, cy, half, direction, name, bins=25):
    """Detector segment perpendicular to `direction`, oriented so that light
    traveling along `direction` produces a positive power reading."""
    dx, dy = direction
    norm = math.hypot(dx, dy)
    ux, uy = -dy / norm, dx / norm
    return {
        "type": "Detector", "name": name,
        "p1": {"x": cx - half * ux, "y": cy - half * uy},
        "p2": {"x": cx + half * ux, "y": cy + half * uy},
        "irradMap": True,
        "binSize": max(2 * half / bins, 0.25),
    }


def _label(x, y, text):
    return {"type": "TextLabel", "x": x, "y": y, "text": text, "fontSize": 24}


def _sag_std(R, h):
    """Sag of a standard-convention spherical surface at semi-aperture h."""
    if R is None:
        return 0.0
    return R - math.copysign(math.sqrt(R * R - h * h), R)


def _lens(x_front, yc, h, R1, R2, ct, glass="BK7", name=None):
    """Thick lens as a Glass object with circular-arc surfaces.

    x_front: front vertex x; R1/R2 standard-convention radii (None = flat);
    ct: center thickness.
    """
    A, B = GLASS[glass]
    xb = x_front + ct
    e1, e2 = x_front + _sag_std(R1, h), xb + _sag_std(R2, h)
    if e2 - e1 < 0.5:
        raise ValueError(
            f"Lens edge thickness {e2 - e1:.2f} <= 0; increase center "
            f"thickness (ct={ct}) or reduce semi-aperture h={h}."
        )
    path = [{"x": e1, "y": yc - h, "arc": False},
            {"x": e2, "y": yc - h, "arc": False}]
    if R2 is not None:
        path.append({"x": xb, "y": yc, "arc": True})
    path += [{"x": e2, "y": yc + h, "arc": False},
             {"x": e1, "y": yc + h, "arc": False}]
    if R1 is not None:
        path.append({"x": x_front, "y": yc, "arc": True})
    obj = {"type": "Glass", "path": path, "refIndex": A, "cauchyB": B}
    if name:
        obj["name"] = name
    return obj


def _corrector_plate(x_front, yc, h, strength, ct=6.0, glass="BK7",
                     neutral_zone=1.5):
    """Schmidt corrector: flat front, aspheric back
    z(y) = strength * (y^4 - neutral_zone * h^2 * y^2)."""
    A, B = GLASS[glass]
    zh = strength * (h ** 4 - neutral_zone * h ** 2 * h ** 2)
    if not -0.5 * ct < zh < 0.5 * ct:
        raise ValueError("Corrector strength too large for plate thickness.")
    xb = x_front + ct
    pieces = [
        {"eqnX": f"{_num(x_front)}+t*({_num(ct + zh)})", "eqnY": _num(yc - h),
         "tMin": 0, "tMax": 1, "tStep": 1},
        {"eqnX": f"{_num(xb)}+({_num(strength)})*((t)^4"
                 f"-({_num(neutral_zone * h * h)})*(t)^2)",
         "eqnY": f"{_num(yc)}+t", "tMin": -h, "tMax": h, "tStep": h / 60},
        {"eqnX": f"{_num(xb + zh)}-t*({_num(ct + zh)})", "eqnY": _num(yc + h),
         "tMin": 0, "tMax": 1, "tStep": 1},
        {"eqnX": _num(x_front), "eqnY": f"{_num(yc + h)}-t*{_num(2 * h)}",
         "tMin": 0, "tMax": 1, "tStep": 1},
    ]
    return {"type": "ParamGlass", "pieces": pieces, "refIndex": A, "cauchyB": B}


# ── Paraxial ray tracer (for focus placement and cone sizes) ─────────────────

def _trace(elements, h0, u0=0.0):
    """Sequential paraxial trace on an unfolded axis.

    elements: ("gap", L) | ("refract", R_std, n1, n2) | ("mirror", R_eff)
    Mirror step u' = u + 2h/R_eff where R_eff < 0 converges (concave toward
    the incoming light) and R_eff > 0 diverges (convex toward incoming).
    Returns list of (h, u) states after each element.
    """
    h, u = h0, u0
    states = [(h, u)]
    for el in elements:
        kind = el[0]
        if kind == "gap":
            h += u * el[1]
        elif kind == "refract":
            _, R, n1, n2 = el
            curv = 0.0 if R is None else 1.0 / R
            u = (n1 * u - h * (n2 - n1) * curv) / n2
        elif kind == "mirror":
            u = u + 2 * h / el[1]
        states.append((h, u))
    return states


def _focus_distance(h, u):
    if abs(u) < 1e-12:
        raise ValueError("Paraxial beam is collimated; no focus.")
    return -h / u


# ── Engine-in-the-loop spot metric and auto-tune ─────────────────────────────

def spot_stats(irradiance_map, bin_positions):
    """Weighted mean and RMS half-width of a detector irradiance map.

    Bins are sign-filtered to the focused-light direction: the detector is
    oriented so converging light counts positive, while any incoming beam
    that happens to cross the detector plane counts negative and must be
    excluded (it would otherwise add a huge uniform pedestal).
    """
    weights = [max(v or 0, 0) for v in irradiance_map]
    tot = sum(weights)
    if tot <= 0:
        return None, None
    mean = sum(p * w for p, w in zip(bin_positions, weights)) / tot
    var = sum(w * (p - mean) ** 2
              for p, w in zip(bin_positions, weights)) / tot
    return mean, math.sqrt(var)


def clipped_spot_rms(irradiance_map, bin_positions, frac=0.9):
    """RMS half-width of the minimal contiguous bin window around the peak
    containing `frac` of the positive energy. Unlike the full-map RMS this is
    not dominated by faint scattered-light wings, so it discriminates between
    designs whose cores are already sharp."""
    w = [max(v or 0, 0) for v in irradiance_map]
    tot = sum(w)
    if tot <= 0:
        return None
    i = max(range(len(w)), key=lambda k: w[k])
    lo = hi = i
    s = w[i]
    while s < frac * tot and (lo > 0 or hi < len(w) - 1):
        left = w[lo - 1] if lo > 0 else -1.0
        right = w[hi + 1] if hi < len(w) - 1 else -1.0
        if left >= right:
            lo -= 1
            s += w[lo]
        else:
            hi += 1
            s += w[hi]
    ww, pp = w[lo:hi + 1], bin_positions[lo:hi + 1]
    t = sum(ww)
    m = sum(p * q for p, q in zip(pp, ww)) / t
    return math.sqrt(sum(q * (p - m) ** 2 for p, q in zip(pp, ww)) / t)


def _rms_spot(objs, ray_density=1.0, clip=None):
    """Run the scene, return RMS half-width of the irradiance distribution on
    the (single) detector, or None when no light arrives. clip=0.9 uses the
    90%-energy clipped RMS instead of the full-map RMS."""
    scene = {"version": 5, "width": 1500, "height": 900,
             "rayModeDensity": ray_density, "maxRayDepth": 200, "objs": objs}
    result = run_scene(scene)
    dets = result.get("detectors") or []
    if not dets or not dets[0].get("irradianceMap"):
        return None
    imap, pos = dets[0]["irradianceMap"], dets[0]["binPositions"]
    if clip is not None:
        return clipped_spot_rms(imap, pos, clip)
    _, rms = spot_stats(imap, pos)
    return rms


def _golden_min(fn, lo, hi, iters=9):
    g = 0.6180339887498949
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = fn(c), fn(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = fn(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = fn(d)
    return (a + b) / 2


_BAD = 1e9


def _spot_or_bad(objs, clip=None):
    r = _rms_spot(objs, clip=clip)
    return _BAD if r is None else r


# ── Reflectors ───────────────────────────────────────────────────────────────

def build_newtonian(p):
    D = p.get("aperture", 200.0)
    f = p.get("focal_length", 800.0)
    h_off = p.get("focus_offset", D / 2 + 60)
    xv, yc = p.get("vertex_x", 1250.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)

    sag = (D / 2) ** 2 / (4 * f)
    x_fold = xv - f + h_off
    hw = (D / 2) * (h_off / f)
    m = 1.6 * hw + 6

    objs = _beams(p.get("source_x", xv - f - 250), yc, D / 2, m, tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f, -1.0, [(-D / 2, D / 2)])
    objs += [
        {"type": "Mirror",
         "p1": {"x": x_fold - m, "y": yc + m},
         "p2": {"x": x_fold + m, "y": yc - m}},
        _detector(x_fold, yc + h_off, 3 * hw + f * abs(math.tan(math.radians(tilt))),
                  (0, 1), "focal_plane"),
        _label(xv - f / 2, yc + D / 2 + 70,
               f"Newtonian  D={D:g}  f={f:g}  (f/{f / D:.1f})"),
    ]
    return objs, {"focus": {"x": x_fold, "y": yc + h_off}, "sag": sag,
                  "f_ratio": f / D}


def build_prime_focus(p):
    D = p.get("aperture", 200.0)
    f = p.get("focal_length", 800.0)
    xv, yc = p.get("vertex_x", 1250.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)

    objs = _beams(p.get("source_x", xv - f - 250), yc, D / 2, tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f, -1.0, [(-D / 2, D / 2)])
    objs += [
        _detector(xv - f, yc, D / 8 + f * abs(math.tan(math.radians(tilt))),
                  (-1, 0), "prime_focus"),
        _label(xv - f / 2, yc + D / 2 + 70,
               f"Prime focus  D={D:g}  f={f:g}  (f/{f / D:.1f})"),
    ]
    return objs, {"focus": {"x": xv - f, "y": yc}, "f_ratio": f / D}


def build_herschelian(p):
    D = p.get("aperture", 180.0)
    f = p.get("focal_length", 900.0)
    y_off = p.get("off_axis_offset", 0.75 * D)
    xv, yc = p.get("vertex_x", 1250.0), p.get("axis_y", 320.0)
    tilt = p.get("field_angle_deg", 0.0)

    if y_off - D / 2 < 20:
        raise ValueError("off_axis_offset too small: focus would sit inside "
                         "the incoming beam (need off_axis_offset > D/2 + 20).")

    # Off-axis segment of the parent parabola; parent focus stays on axis yc.
    objs = _beams(p.get("source_x", xv - f - 200), yc + y_off, D / 2,
                  tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f, -1.0, [(y_off - D / 2, y_off + D / 2)])
    objs.append(_label(xv - f / 2, yc + y_off + D / 2 + 70,
                       f"Herschelian (off-axis)  D={D:g}  f={f:g}"))
    # Chief-ray direction from segment center to the parent focus
    x_ctr = xv - y_off ** 2 / (4 * f)
    d = (xv - f - x_ctr, -y_off)
    objs.append(_detector(xv - f, yc, D / 6 + f * abs(math.tan(math.radians(tilt))),
                          d, "focal_plane"))
    return objs, {"focus": {"x": xv - f, "y": yc},
                  "unobstructed": True, "f_ratio": f / D}


def _two_mirror_layout(p, need_d_gt_f1=False):
    D = p.get("aperture", 240.0)
    f1 = p.get("primary_focal_length", 600.0)
    d = p.get("secondary_distance", 0.75 * f1 if not need_d_gt_f1 else 1.5 * f1)
    b = p.get("back_focal_distance", 120.0)
    if need_d_gt_f1:
        if d <= f1:
            raise ValueError("Gregorian needs secondary_distance > "
                             "primary_focal_length (secondary beyond prime focus).")
        pp = d - f1
    else:
        if not 0 < d < f1:
            raise ValueError("secondary_distance must lie between 0 and "
                             "primary_focal_length.")
        pp = f1 - d
    q = d + b
    m = q / pp
    return D, f1, d, b, pp, q, m


def build_two_mirror(p, flavor="classical"):
    """Classical Cassegrain / Ritchey-Chretien / Dall-Kirkham."""
    D, f1, d, b, pp, q, m = _two_mirror_layout(p)
    xv, yc = p.get("vertex_x", 1150.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)

    if flavor == "classical":
        K1 = -1.0
        K2 = -((m + 1) / (m - 1)) ** 2
    elif flavor == "ritchey_chretien":
        K1 = -1.0 - (2.0 / m ** 3) * (q / d)
        K2 = -1.0 - (2.0 / (m - 1) ** 3) * (m * (2 * m - 1) + q / d)
    elif flavor == "dall_kirkham":
        k = pp / f1
        K1 = -1.0 + k * (m - 1) * (m + 1) ** 2 / m ** 3
        K2 = 0.0
    else:
        raise ValueError(flavor)

    xs = xv - d
    xF2 = xv + b
    r_sec = (D / 2) * pp / f1          # marginal cone half-width at secondary
    r_sec_edge = 1.35 * r_sec
    R2 = 2 * pp * q / (q - pp)         # sag-convention vertex radius (convex)
    r_hole = max(1.6 * r_sec_edge * b / q, 10.0)
    if r_hole >= D / 2:
        raise ValueError("Primary hole would exceed the aperture; "
                         "increase aperture or reduce back_focal_distance.")

    f_sys = m * f1
    names = {"classical": "Cassegrain", "ritchey_chretien": "Ritchey-Chretien",
             "dall_kirkham": "Dall-Kirkham"}

    objs = _beams(p.get("source_x", xv - f1 - 300), yc, D / 2, r_sec_edge,
                  tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f1, K1, _annular_spans(r_hole, D / 2))
    objs += _conic_mirror(xs, yc, R2, K2, [(-r_sec_edge, r_sec_edge)])
    objs += [
        _detector(xF2, yc,
                  3 * r_hole + f_sys * abs(math.tan(math.radians(tilt))),
                  (1, 0), "focal_plane"),
        _label(xv - f1 / 2, yc + D / 2 + 70,
               f"{names[flavor]}  D={D:g}  f1={f1:g}  m={m:.2f}  "
               f"(f/{f_sys / D:.1f})  K1={K1:.4f}  K2={K2:.3f}"),
    ]
    info = {
        "final_focus": {"x": xF2, "y": yc},
        "prime_focus": {"x": xv - f1, "y": yc},
        "magnification": m, "system_focal_length": f_sys,
        "f_ratio": f_sys / D, "K1": K1, "K2": K2,
        "secondary_radius_of_curvature": R2,
        "primary_hole_radius": r_hole,
    }
    return objs, info


def build_gregorian(p):
    f1_default = p.get("primary_focal_length", 500.0)
    D, f1, d, b, pp, q, m = _two_mirror_layout(
        {**p, "aperture": p.get("aperture", 200.0),
         "primary_focal_length": f1_default,
         # Keep the secondary near the prime focus: Gregorian obstruction
         # grows quickly with (d - f1)
         "secondary_distance": p.get("secondary_distance", 1.25 * f1_default),
         "back_focal_distance": p.get("back_focal_distance", 130.0)},
        need_d_gt_f1=True)
    xv, yc = p.get("vertex_x", 1250.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)

    xs = xv - d
    xF2 = xv + b
    # Concave elliptical secondary, foci at prime focus and final focus:
    # a = (p+q)/2, c = (q-p)/2, b_ell^2 = p*q  ->  R = -2pq/(p+q), K = -(c/a)^2
    K2 = -((q - pp) / (q + pp)) ** 2
    R2 = -2 * pp * q / (pp + q)
    r_sec = (D / 2) * pp / f1
    r_sec_edge = 1.4 * r_sec
    r_hole = max(1.6 * r_sec_edge * b / q, 10.0)
    f_sys = m * f1

    objs = _beams(p.get("source_x", xv - d - 150), yc, D / 2, r_sec_edge,
                  tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f1, -1.0, _annular_spans(r_hole, D / 2))
    objs += _conic_mirror(xs, yc, R2, K2, [(-r_sec_edge, r_sec_edge)])
    objs += [
        _detector(xF2, yc,
                  3 * r_hole + f_sys * abs(math.tan(math.radians(tilt))),
                  (1, 0), "focal_plane"),
        _label(xv - d / 2, yc + D / 2 + 70,
               f"Gregorian  D={D:g}  f1={f1:g}  m={m:.2f}  (f/{f_sys / D:.1f})"),
    ]
    info = {"final_focus": {"x": xF2, "y": yc},
            "prime_focus": {"x": xv - f1, "y": yc},
            "magnification": m, "system_focal_length": f_sys,
            "f_ratio": f_sys / D, "K2": K2, "image_erect": True}
    return objs, info


def build_nasmyth(p):
    """Classical Cassegrain optics with a flat tertiary folding the beam 90
    degrees to a side (platform) focus before it reaches the primary."""
    D, f1, d, b, pp, q, m = _two_mirror_layout(p)
    xv, yc = p.get("vertex_x", 1150.0), p.get("axis_y", 380.0)
    t_off = p.get("tertiary_offset", 0.3 * f1)  # primary vertex -> tertiary
    tilt = p.get("field_angle_deg", 0.0)

    K2 = -((m + 1) / (m - 1)) ** 2
    R2 = 2 * pp * q / (q - pp)
    xs = xv - d
    x_t = xv - t_off
    if not xs + 20 < x_t < xv - 5:
        raise ValueError("tertiary_offset must place the flat between the "
                         "secondary and the primary.")
    xF2 = xv + b                      # would-be Cassegrain focus
    f_sys = m * f1
    r_sec = (D / 2) * pp / f1
    r_sec_edge = 1.35 * r_sec

    # Cone half-width of the secondary->focus beam at the tertiary
    w_fold = r_sec_edge * (xF2 - x_t) / (xF2 - xs)
    m_t = 1.25 * w_fold               # 45-degree flat half-extent (in y)
    # It must hide inside the hollow center of the primary->secondary cone
    hollow = r_sec_edge * (x_t - (xv - f1)) / f1
    if m_t > 0.95 * hollow:
        raise ValueError(
            f"Tertiary (half-extent {m_t:.1f}) would poke out of the beam "
            f"shadow ({hollow:.1f}); increase secondary size or move the "
            "tertiary (tertiary_offset) closer to the primary.")

    L_rem = xF2 - x_t                 # remaining path after the fold
    focus = (x_t, yc + L_rem)

    objs = _beams(p.get("source_x", xv - f1 - 300), yc, D / 2,
                  max(r_sec_edge, m_t * 1.1), tilt_deg=tilt)
    objs += _conic_mirror(xv, yc, 2 * f1, -1.0, [(-D / 2, D / 2)])  # no hole
    objs += _conic_mirror(xs, yc, R2, K2, [(-r_sec_edge, r_sec_edge)])
    objs += [
        {"type": "Mirror",  # 45-degree tertiary, folds +x into +y
         "p1": {"x": x_t - m_t, "y": yc - m_t},
         "p2": {"x": x_t + m_t, "y": yc + m_t}},
        _detector(focus[0], focus[1],
                  3 * w_fold + f_sys * abs(math.tan(math.radians(tilt))),
                  (0, 1), "nasmyth_focus"),
        _label(xv - f1 / 2, yc - D / 2 - 50,
               f"Nasmyth  D={D:g}  f1={f1:g}  m={m:.2f}  (f/{f_sys / D:.1f})"),
    ]
    info = {"nasmyth_focus": {"x": focus[0], "y": focus[1]},
            "magnification": m, "system_focal_length": f_sys,
            "f_ratio": f_sys / D, "tertiary_x": x_t}
    return objs, info


# ── Catadioptrics ────────────────────────────────────────────────────────────

def build_schmidt_camera(p):
    D = p.get("aperture", 200.0)
    f = p.get("focal_length", 400.0)
    xv, yc = p.get("vertex_x", 1300.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    n_g = _n("BK7")
    h = D / 2 * 1.05

    x_cor = xv - 2 * f                 # corrector at the center of curvature
    s0 = 1.0 / (32 * (n_g - 1) * f ** 3)
    ct_pl = 6.0

    def focus_x(strength):
        # The corrector's r^2 (neutral zone) term adds weak paraxial power;
        # place the detector at the traced focus, not the bare-mirror focus.
        R_b = None if strength == 0 else -1.0 / (3.0 * strength * h * h)
        els = [("refract", None, 1.0, n_g), ("gap", ct_pl),
               ("refract", R_b, n_g, 1.0),
               ("gap", xv - (x_cor + ct_pl)), ("mirror", -2.0 * f)]
        hh, uu = _trace(els, D / 4)[-1]
        return xv - _focus_distance(hh, uu)

    def objs_for(strength, with_extras=True):
        xF = focus_x(strength)
        objs = _beams(p.get("source_x", x_cor - 120), yc, D / 2, tilt_deg=tilt,
                      wavelengths=RGB_WAVELENGTHS if p.get("chromatic") else None)
        objs.append(_corrector_plate(x_cor, yc, h, strength, ct=ct_pl))
        objs += _conic_mirror(xv, yc, 2 * f, 0.0, [(-D / 2, D / 2)])
        objs.append(_detector(xF, yc,
                              D / 10 + f * abs(math.tan(math.radians(tilt))),
                              (-1, 0), "focal_surface", bins=161))
        if with_extras:
            objs.append(_label(xv - f, yc + D / 2 + 70,
                               f"Schmidt camera  D={D:g}  f={f:g}  (f/{f / D:.1f})"))
        return objs

    strength = _golden_min(lambda s: _spot_or_bad(objs_for(s, False)),
                           0.2 * s0, 2.5 * s0)
    rms = _rms_spot(objs_for(strength, False))
    rms_uncorrected = _rms_spot(objs_for(1e-14, False))
    objs = objs_for(strength)
    info = {"focus": {"x": focus_x(strength), "y": yc}, "f_ratio": f / D,
            "corrector_strength": strength,
            "corrector_strength_theory": s0,
            "rms_spot_radius": rms,
            "rms_spot_radius_uncorrected": rms_uncorrected,
            "note": "Corrector strength auto-tuned by ray tracing; focal "
                    "surface is curved (detector shows on-axis spot)."}
    return objs, info


def build_schmidt_cassegrain(p):
    D = p.get("aperture", 200.0)
    f1 = p.get("primary_focal_length", 400.0)
    d = p.get("secondary_distance", 310.0)
    b = p.get("back_focal_distance", 150.0)
    xv, yc = p.get("vertex_x", 1150.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    n_g = _n("BK7")

    pp, q = f1 - d, d + b
    m = q / pp
    R2 = 2 * pp * q / (q - pp)         # spherical secondary (sag convention)
    xs = xv - d
    r_sec = (D / 2) * pp / f1
    r_sec_edge = 1.4 * r_sec
    r_hole = max(1.6 * r_sec_edge * b / q, 10.0)
    x_cor = xs - 25
    h = D / 2 * 1.05
    f_sys = m * f1
    s0 = 1.0 / (32 * (n_g - 1) * f1 ** 3)
    ct_pl = 6.0

    def focus_x(strength):
        # Paraxial focus including the corrector's weak paraxial power
        R_b = None if strength == 0 else -1.0 / (3.0 * strength * h * h)
        els = [
            ("refract", None, 1.0, n_g), ("gap", ct_pl),
            ("refract", R_b, n_g, 1.0),
            ("gap", xv - (x_cor + ct_pl)), ("mirror", -2.0 * f1),
            ("gap", d), ("mirror", R2),
        ]
        st = _trace(els, D / 4)
        hh, uu = st[-1]
        return xs + _focus_distance(hh, uu)

    def objs_for(strength, with_extras=True):
        xF = focus_x(strength)
        objs = _beams(p.get("source_x", x_cor - 120), yc, D / 2, r_sec_edge,
                      tilt_deg=tilt,
                      wavelengths=RGB_WAVELENGTHS if p.get("chromatic") else None)
        objs.append(_corrector_plate(x_cor, yc, h, strength, ct=ct_pl))
        objs += _conic_mirror(xv, yc, 2 * f1, 0.0,
                              _annular_spans(r_hole, D / 2))
        objs += _conic_mirror(xs, yc, R2, 0.0,
                              [(-r_sec_edge, r_sec_edge)])
        objs.append(_detector(xF, yc,
                              2.5 * r_hole + f_sys * abs(math.tan(math.radians(tilt))),
                              (1, 0), "focal_plane", bins=161))
        if with_extras:
            objs.append(_label(xv - f1 / 2, yc + D / 2 + 70,
                               f"Schmidt-Cassegrain  D={D:g}  f1={f1:g}  "
                               f"m={m:.2f}  (f/{f_sys / D:.1f})"))
        return objs

    strength = _golden_min(lambda s: _spot_or_bad(objs_for(s, False)),
                           0.2 * s0, 3.0 * s0)
    rms = _rms_spot(objs_for(strength, False))
    xF = focus_x(strength)
    info = {"final_focus": {"x": xF, "y": yc}, "magnification": m,
            "system_focal_length": f_sys, "f_ratio": f_sys / D,
            "corrector_strength": strength, "rms_spot_radius": rms,
            "primary_hole_radius": r_hole,
            "note": "Both mirrors spherical; full-aperture Schmidt corrector "
                    "auto-tuned by ray tracing (third-order residuals remain)."}
    return objs_for(strength), info


def build_maksutov_cassegrain(p):
    """Gregory (spot) Maksutov: deep meniscus corrector, spherical primary,
    secondary = aluminized spot on the meniscus rear surface."""
    D = p.get("aperture", 150.0)
    f1 = p.get("primary_focal_length", 4.3 * p.get("aperture", 150.0))
    L_mp = p.get("meniscus_to_primary", 3.2 * D)  # meniscus rear -> primary
    t_men = p.get("meniscus_thickness", 0.09 * D)
    xv, yc = p.get("vertex_x", 1150.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    n_g = _n("BK7")
    h_men = D / 2 * 1.08

    x_back = xv - L_mp                 # meniscus rear vertex
    x_front = x_back - t_men

    def layout(R1):
        # Achromatic Gregory meniscus: R2 = R1 - t(n^2-1)/n^2 (both negative)
        R2 = R1 - t_men * (n_g ** 2 - 1) / n_g ** 2
        els = [
            ("refract", R1, 1.0, n_g), ("gap", t_men),
            ("refract", R2, n_g, 1.0),
            ("gap", L_mp), ("mirror", -2.0 * f1),
            ("gap", L_mp),                       # back to the spot
        ]
        h_spot, u_spot = _trace(els, D / 4)[-1]
        h2, u2 = _trace([("mirror", -R2)], h_spot, u_spot)[-1]  # convex spot
        h_hole = h2 + u2 * L_mp        # beam height at the primary plane
        Lf = _focus_distance(h2, u2)   # spot -> focus distance
        xF = x_back + Lf
        if xF < xv + 40:
            raise ValueError("focus not behind primary")
        f_sys = abs((D / 4) / u2)
        return R2, abs(h_spot), abs(h_hole), xF, f_sys

    def objs_for(R1, with_extras=True):
        R2, h_spot, h_hole, xF, f_sys = layout(R1)
        r_spot = 1.35 * h_spot * 2     # traced at D/4 -> scale to marginal
        r_hole = max(1.6 * h_hole * 2, 8.0)
        objs = _beams(p.get("source_x", x_front - 120), yc, D / 2,
                      max(r_spot * 1.15, 12.0), tilt_deg=tilt,
                      wavelengths=RGB_WAVELENGTHS if p.get("chromatic") else None)
        objs.append(_lens(x_front, yc, h_men, R1, R2, t_men, "BK7",
                          name="meniscus"))
        objs += _conic_mirror(xv, yc, 2 * f1, 0.0,
                              _annular_spans(r_hole, D / 2))
        # Spot mirror: same curvature as the rear surface, 0.5 units proud of
        # the glass so rays reflect before entering it
        objs += _conic_mirror(x_back + 0.5, yc, -R2, 0.0,
                              [(-r_spot, r_spot)])
        objs.append(_detector(xF, yc,
                              2.5 * r_hole + f_sys * abs(math.tan(math.radians(tilt))),
                              (1, 0), "focal_plane", bins=161))
        if with_extras:
            objs.append(_label(xv - L_mp / 2, yc + D / 2 + 70,
                               f"Maksutov-Cassegrain  D={D:g}  f1={f1:g}  "
                               f"(f/{f_sys / D:.1f})"))
        return objs, (R2, xF, r_spot, r_hole, f_sys)

    def metric(R1):
        try:
            objs, _ = objs_for(R1, False)
        except ValueError:
            return _BAD
        return _spot_or_bad(objs)

    R1 = _golden_min(metric, -3.6 * D, -2.6 * D, iters=12)
    if metric(R1) >= _BAD:
        raise ValueError(
            "Maksutov auto-tune failed: no meniscus radius in range gives a "
            "focus behind the primary. Adjust primary_focal_length / "
            "meniscus_to_primary.")
    objs, (R2, xF, r_spot, r_hole, f_sys) = objs_for(R1)
    rms = _rms_spot(objs_for(R1, False)[0])
    info = {"final_focus": {"x": xF, "y": yc},
            "meniscus_R1": R1, "meniscus_R2": R2,
            "spot_radius": r_spot, "primary_hole_radius": r_hole,
            "system_focal_length": f_sys, "f_ratio": f_sys / D,
            "rms_spot_radius": rms,
            "note": "Meniscus R1 auto-tuned by ray tracing with the "
                    "achromatic Gregory constraint R2 = R1 - t(n^2-1)/n^2."}
    return objs, info


# ── Refractors ───────────────────────────────────────────────────────────────

def build_refractor_ideal(p, galilean=False):
    D = p.get("aperture", 160.0)
    f_obj = p.get("objective_focal_length", 700.0)
    f_eye = p.get("eyepiece_focal_length", 100.0)
    x_obj, yc = p.get("objective_x", 350.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)

    if galilean:
        x_eye, eye_fl, label = x_obj + f_obj - f_eye, -f_eye, "Galilean"
    else:
        x_eye, eye_fl, label = x_obj + f_obj + f_eye, f_eye, "Keplerian"
    mag = f_obj / f_eye
    d_eye_half = D / 2 * f_eye / f_obj + 12 + f_obj * abs(math.tan(math.radians(tilt)))

    objs = _beams(p.get("source_x", x_obj - 250), yc, D / 2, tilt_deg=tilt)
    objs += [
        {"type": "IdealLens", "name": "objective",
         "p1": {"x": x_obj, "y": yc - D / 2 - 15},
         "p2": {"x": x_obj, "y": yc + D / 2 + 15}, "focalLength": f_obj},
        {"type": "IdealLens", "name": "eyepiece",
         "p1": {"x": x_eye, "y": yc - d_eye_half},
         "p2": {"x": x_eye, "y": yc + d_eye_half}, "focalLength": eye_fl},
        _detector(x_eye + 120, yc, d_eye_half, (1, 0), "exit_beam"),
        _label(x_obj, yc + D / 2 + 80,
               f"{label} refractor  D={D:g}  f_obj={f_obj:g}  "
               f"f_eye={f_eye:g}  mag={mag:.1f}x"),
    ]
    info = {"eyepiece_x": x_eye, "magnification": mag}
    if not galilean:
        info["internal_focus"] = {"x": x_obj + f_obj, "y": yc}
    return objs, info


def _refractor_focus(lens_seq, x_ref, h0):
    """Paraxial focus x for a sequence of thick lenses.
    lens_seq: list of (x_front, R1, R2, ct, n)."""
    els = []
    x_cursor = x_ref
    for x_front, R1, R2, ct, n in lens_seq:
        els.append(("gap", x_front - x_cursor))
        els.append(("refract", R1, 1.0, n))
        els.append(("gap", ct))
        els.append(("refract", R2, n, 1.0))
        x_cursor = x_front + ct
    h, u = _trace(els, h0)[-1]
    return x_cursor + _focus_distance(h, u)


def build_singlet(p):
    D = p.get("aperture", 120.0)
    f = p.get("focal_length", 600.0)
    x_l, yc = p.get("objective_x", 350.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    chromatic = p.get("chromatic", True)
    n_g = _n("BK7")
    h = D / 2 + 8
    R = 2 * (n_g - 1) * f              # equiconvex
    ct = 2 * abs(_sag_std(R, h)) + 6

    xF = _refractor_focus([(x_l, R, -R, ct, n_g)], x_l, D / 4)
    objs = _beams(p.get("source_x", x_l - 250), yc, D / 2, tilt_deg=tilt,
                  wavelengths=RGB_WAVELENGTHS if chromatic else None)
    objs += [
        _lens(x_l, yc, h, R, -R, ct, "BK7", name="singlet"),
        _detector(xF, yc, D / 8 + f * abs(math.tan(math.radians(tilt))),
                  (1, 0), "focal_plane", bins=41),
        _label(x_l, yc + D / 2 + 80,
               f"Singlet (BK7)  D={D:g}  f~{f:g} - note chromatic spread"),
    ]
    info = {"focus": {"x": xF, "y": yc}, "R": R,
            "chromatic_demo": chromatic,
            "note": "Single BK7 lens; enable scene simulateColors to see "
                    "longitudinal chromatic aberration."}
    return objs, info


def _achromat_surfaces(f, D, x_l):
    """Fraunhofer cemented-style doublet (0.5 unit air gap), BK7 + F2."""
    n1, n2 = _n("BK7"), _n("F2")
    V1, V2 = _abbe("BK7"), _abbe("F2")
    phi = 1.0 / f
    phi1 = phi * V1 / (V1 - V2)
    phi2 = -phi * V2 / (V1 - V2)
    # Crown: equiconvex; flint front matches crown rear (near-contact)
    R1 = 2 * (n1 - 1) / phi1
    R2 = -R1
    R3 = R2
    R4 = 1.0 / (1.0 / R3 - phi2 / (n2 - 1))
    h = D / 2 + 8
    ct1 = 2 * abs(_sag_std(R1, h)) + 6
    gap = 0.8
    ct2 = abs(_sag_std(R3, h)) + abs(_sag_std(R4, h)) + 6
    x2 = x_l + ct1 + gap
    lenses = [(x_l, R1, R2, ct1, "BK7"), (x2, R3, R4, ct2, "F2")]
    return lenses, h


def build_achromat(p):
    D = p.get("aperture", 120.0)
    f = p.get("focal_length", 600.0)
    x_l, yc = p.get("objective_x", 350.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    chromatic = p.get("chromatic", True)

    lenses, h = _achromat_surfaces(f, D, x_l)
    seq = [(x, R1, R2, ct, _n(g)) for x, R1, R2, ct, g in lenses]
    xF = _refractor_focus(seq, x_l, D / 4)

    objs = _beams(p.get("source_x", x_l - 250), yc, D / 2, tilt_deg=tilt,
                  wavelengths=RGB_WAVELENGTHS if chromatic else None)
    objs += [_lens(x, yc, h, R1, R2, ct, g, name=g)
             for x, R1, R2, ct, g in lenses]
    objs += [
        _detector(xF, yc, D / 8 + f * abs(math.tan(math.radians(tilt))),
                  (1, 0), "focal_plane", bins=41),
        _label(x_l, yc + D / 2 + 80,
               f"Fraunhofer achromat (BK7+F2)  D={D:g}  f~{f:g}"),
    ]
    info = {"focus": {"x": xF, "y": yc},
            "surfaces": {f"R{i + 1}": r for i, r in enumerate(
                [lenses[0][1], lenses[0][2], lenses[1][1], lenses[1][2]])},
            "note": "With the simulator's two-term Cauchy dispersion an "
                    "achromat doublet corrects color at ALL wavelengths, so "
                    "a triplet apochromat would add nothing chromatically."}
    return objs, info


def build_petzval(p):
    D = p.get("aperture", 110.0)
    f_front = p.get("front_focal_length", 500.0)
    f_rear = p.get("rear_focal_length", 450.0)
    sep = p.get("separation", 300.0)
    x_l, yc = p.get("objective_x", 250.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    chromatic = p.get("chromatic", False)

    front, h1 = _achromat_surfaces(f_front, D, x_l)
    rear, h2 = _achromat_surfaces(f_rear, D * 0.7, x_l + sep)
    seq = [(x, R1, R2, ct, _n(g)) for x, R1, R2, ct, g in front + rear]
    xF = _refractor_focus(seq, x_l, D / 4)
    # Effective focal length from the marginal ray slope
    els = []
    xc = x_l
    for x, R1, R2, ct, n in seq:
        els += [("gap", x - xc), ("refract", R1, 1.0, n),
                ("gap", ct), ("refract", R2, n, 1.0)]
        xc = x + ct
    hh, uu = _trace(els, D / 4)[-1]
    f_sys = abs((D / 4) / uu)

    objs = _beams(p.get("source_x", x_l - 180), yc, D / 2, tilt_deg=tilt,
                  wavelengths=RGB_WAVELENGTHS if chromatic else None)
    objs += [_lens(x, yc, hh_l, R1, R2, ct, g, name=g)
             for (x, R1, R2, ct, g), hh_l in
             [(l, h1) for l in front] + [(l, h2) for l in rear]]
    objs += [
        _detector(xF, yc, D / 8 + f_sys * abs(math.tan(math.radians(tilt))),
                  (1, 0), "focal_plane", bins=41),
        _label(x_l, yc + D / 2 + 90,
               f"Petzval  D={D:g}  f_sys~{f_sys:.0f}  (f/{f_sys / D:.1f})"),
    ]
    info = {"focus": {"x": xF, "y": yc}, "system_focal_length": f_sys,
            "f_ratio": f_sys / D,
            "note": "Two air-spaced achromat groups; classic fast portrait/"
                    "astrograph configuration."}
    return objs, info


def _element_lens(x_front, yc, h, phi, glass, bend=0.0, min_ct=6.0):
    """Single lens element of power phi with a bending parameter.

    bend = 0 gives an equi-bent element; positive bend shifts curvature to
    the front surface while preserving the thin-lens power.
    """
    n = _n(glass)
    c_tot = phi / (n - 1)              # c1 - c2
    c1 = c_tot / 2 * (1 + bend)
    c2 = c1 - c_tot
    R1 = None if abs(c1) < 1e-9 else 1.0 / c1
    R2 = None if abs(c2) < 1e-9 else 1.0 / c2
    ct = min_ct + max(0.0, _sag_std(R1, h) if R1 else 0.0) \
        + max(0.0, -_sag_std(R2, h) if R2 else 0.0)
    return (x_front, R1, R2, ct, glass), _lens(x_front, yc, h, R1, R2, ct,
                                               glass, name=glass)


def build_apo_triplet(p):
    """ED apochromatic triplet: FPL53 (+) / F2 (-) / FPL53 (+), air-spaced.

    Power split satisfies the achromat condition with the ED glass; the ED
    power is split across two elements, and all three element bendings are
    auto-tuned by ray tracing (coordinate descent on the clipped spot RMS).
    """
    D = p.get("aperture", 140.0)
    f = p.get("focal_length", 700.0)   # f/5 default: fast, where a triplet earns its keep
    x_l, yc = p.get("objective_x", 300.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", 0.0)
    chromatic = p.get("chromatic", True)

    V_ed, V_fl = _abbe("FPL53"), _abbe("F2")
    phi = 1.0 / f
    phi_ed = phi * V_ed / (V_ed - V_fl)     # total ED power
    phi_fl = -phi * V_fl / (V_ed - V_fl)
    h = D / 2 + 8
    gap = 3.0

    def build(bends, with_extras=True):
        seq, lenses = [], []
        x = x_l
        for (phi_i, glass), b in zip([(phi_ed / 2, "FPL53"),
                                      (phi_fl, "F2"),
                                      (phi_ed / 2, "FPL53")], bends):
            spec, lens = _element_lens(x, yc, h, phi_i, glass, b)
            seq.append((spec[0], spec[1], spec[2], spec[3], _n(glass)))
            lenses.append(lens)
            x = spec[0] + spec[3] + gap
        xF = _refractor_focus(seq, x_l, D / 4)
        objs = _beams(p.get("source_x", x_l - 200), yc, D / 2, tilt_deg=tilt,
                      wavelengths=RGB_WAVELENGTHS if chromatic else None)
        objs += lenses
        objs.append(_detector(xF, yc,
                              D / 10 + f * abs(math.tan(math.radians(tilt))),
                              (1, 0), "focal_plane", bins=161))
        if with_extras:
            objs.append(_label(x_l, yc + D / 2 + 80,
                               f"Apo triplet (FPL53/F2/FPL53)  D={D:g}  "
                               f"f~{f:g}  (f/{f / D:.1f})"))
        return objs, xF

    def metric(bends):
        try:
            return _spot_or_bad(build(bends, False)[0], clip=0.9)
        except ValueError:   # geometrically impossible element
            return _BAD

    bends = [0.0, 0.3, 0.0]
    for _ in range(2):       # coordinate descent, 2 sweeps over 3 bendings
        for i in range(3):
            bends[i] = _golden_min(
                lambda v: metric(bends[:i] + [v] + bends[i + 1:]),
                bends[i] - 0.6, bends[i] + 0.6, iters=6)

    objs, xF = build(bends)
    rms = _rms_spot(build(bends, False)[0], clip=0.9)
    info = {"focus": {"x": xF, "y": yc}, "f_ratio": f / D,
            "element_bendings": bends, "rms_spot_radius_90pct": rms,
            "glasses": ["FPL53", "F2", "FPL53"],
            "note": "All three element bendings auto-tuned by ray tracing "
                    "(90%-energy clipped RMS). NB: the engine's two-term "
                    "Cauchy dispersion means any achromat pair already "
                    "cancels color exactly, so the triplet's measurable gain "
                    "here is monochromatic (spherical aberration control at "
                    "fast f-ratios); real-world secondary spectrum does not "
                    "exist in this dispersion model."}
    return objs, info


def build_flatfield_petzval(p):
    """Flat-field Petzval astrograph: two achromat doublets (quadruplet) with
    an optional negative field flattener near focus (quintuplet).

    The group separation (quadruplet) or flattener focal length (quintuplet)
    is auto-tuned by tracing on-axis AND off-axis beams onto one flat focal
    plane and minimizing the combined 90%-energy clipped RMS spot.
    """
    D = p.get("aperture", 110.0)
    f_front = p.get("front_focal_length", 500.0)
    f_rear = p.get("rear_focal_length", 450.0)
    sep0 = p.get("separation", 300.0)
    n_elements = int(p.get("elements", 5))
    field = p.get("design_field_deg", 3.0)
    x_l, yc = p.get("objective_x", 250.0), p.get("axis_y", 420.0)
    tilt = p.get("field_angle_deg", field)  # show the design field by default
    chromatic = p.get("chromatic", False)
    if n_elements not in (4, 5):
        raise ValueError("elements must be 4 (quadruplet) or 5 (quintuplet).")

    flat_glass = "F2"
    n_flat = _n(flat_glass)
    # Real flatteners sit close to the focal plane, where they change field
    # curvature but almost nothing else.
    d_flat = p.get("flattener_distance", 14.0)

    def build(sep, f_flat, tilt_deg, with_extras=True):
        front, h1 = _achromat_surfaces(f_front, D, x_l)
        rear, h2 = _achromat_surfaces(f_rear, D * 0.7, x_l + sep)
        seq = [(x, R1, R2, ct, _n(g)) for x, R1, R2, ct, g in front + rear]
        lens_objs = [_lens(x, yc, hh, R1, R2, ct, g, name=g)
                     for (x, R1, R2, ct, g), hh in
                     [(l, h1) for l in front] + [(l, h2) for l in rear]]
        # System EFL (before flattener; the flattener barely changes it)
        els, xc = [], x_l
        for x, R1, R2, ct, n in seq:
            els += [("gap", x - xc), ("refract", R1, 1.0, n),
                    ("gap", ct), ("refract", R2, n, 1.0)]
            xc = x + ct
        hh, uu = _trace(els, D / 4)[-1]
        f_sys = abs((D / 4) / uu)
        img_h = f_sys * abs(math.tan(math.radians(field)))
        if f_flat is not None:
            # Plano-concave flattener; thin-lens power 1/f_flat (negative)
            xF0 = _refractor_focus(seq, x_l, D / 4)
            R2_fl = -(n_flat - 1) * f_flat
            # Cover the converging cone plus the full field image height
            h_fl = 1.3 * (d_flat / f_sys * (D / 2) + img_h) + 3
            if abs(R2_fl) <= h_fl:
                raise ValueError("flattener too strong for its aperture")
            x_fl = xF0 - d_flat
            seq.append((x_fl, None, R2_fl, 5.0, n_flat))
            lens_objs.append(_lens(x_fl, yc, h_fl, None, R2_fl, 5.0,
                                   flat_glass, name="flattener"))
        xF = _refractor_focus(seq, x_l, D / 4)
        half = D / 8 + 1.4 * img_h
        objs = _beams(p.get("source_x", x_l - 180), yc, D / 2,
                      tilt_deg=tilt_deg,
                      wavelengths=RGB_WAVELENGTHS if chromatic else None)
        objs += lens_objs
        objs.append(_detector(xF, yc, half, (1, 0), "focal_plane", bins=321))
        if with_extras:
            kind = "quintuplet" if f_flat is not None else "quadruplet"
            objs.append(_label(x_l, yc + D / 2 + 90,
                               f"Flat-field Petzval {kind}  D={D:g}  "
                               f"f_sys~{f_sys:.0f}  (f/{f_sys / D:.1f})"))
        return objs, xF, f_sys

    def flat_rms(sep, f_flat, tilt_deg):
        try:
            return _spot_or_bad(build(sep, f_flat, tilt_deg, False)[0],
                                clip=0.9)
        except ValueError:
            return _BAD

    def field_metric(sep, f_flat):
        """Combined on-axis + off-axis blur on the same flat focal plane."""
        r0 = flat_rms(sep, f_flat, 0.0)
        r1 = flat_rms(sep, f_flat, field)
        if r0 >= _BAD or r1 >= _BAD:
            return _BAD
        return math.sqrt((r0 * r0 + r1 * r1) / 2)

    if n_elements == 5:
        g_min = max(60.0, 1.4 * (D / 2 + 40) / (n_flat - 1))
        f_flat = -_golden_min(lambda g: field_metric(sep0, -g),
                              g_min, 900.0, iters=9)
        sep = sep0
    else:
        f_flat = None
        sep = _golden_min(lambda s: field_metric(s, None),
                          0.55 * sep0, 1.45 * sep0, iters=9)

    objs, xF, f_sys = build(sep, f_flat, tilt)
    info = {"focus": {"x": xF, "y": yc}, "system_focal_length": f_sys,
            "f_ratio": f_sys / D, "elements": n_elements,
            "separation": sep, "flattener_focal_length": f_flat,
            "design_field_deg": field,
            "rms_spot_on_axis_90pct": flat_rms(sep, f_flat, 0.0),
            "rms_spot_at_field_90pct": flat_rms(sep, f_flat, field),
            "note": "Auto-tuned by tracing 0-deg and field-angle beams onto "
                    "one flat focal plane, minimizing the combined 90%-energy "
                    "clipped RMS spot. The scene is built at the design field "
                    "angle so the render shows the off-axis image point; set "
                    "field_angle_deg=0 for the on-axis view."}
    if n_elements == 5:
        info["rms_at_field_without_flattener_90pct"] = flat_rms(sep, None,
                                                                field)
    return objs, info


# ── Registry ─────────────────────────────────────────────────────────────────

BUILDERS = {
    # Reflectors
    "newtonian": build_newtonian,
    "prime_focus": build_prime_focus,
    "herschelian": build_herschelian,
    "cassegrain": lambda p: build_two_mirror(p, "classical"),
    "ritchey_chretien": lambda p: build_two_mirror(p, "ritchey_chretien"),
    "dall_kirkham": lambda p: build_two_mirror(p, "dall_kirkham"),
    "gregorian": build_gregorian,
    "nasmyth": build_nasmyth,
    # Catadioptrics
    "schmidt_camera": build_schmidt_camera,
    "schmidt_cassegrain": build_schmidt_cassegrain,
    "maksutov_cassegrain": build_maksutov_cassegrain,
    # Refractors
    "keplerian_refractor": lambda p: build_refractor_ideal(p, galilean=False),
    "galilean_refractor": lambda p: build_refractor_ideal(p, galilean=True),
    "singlet_refractor": build_singlet,
    "achromat_doublet": build_achromat,
    "petzval_refractor": build_petzval,
    "apo_triplet": build_apo_triplet,
    "flatfield_petzval": build_flatfield_petzval,
}

# Designs whose scenes should default to chromatic simulation
CHROMATIC_DEFAULT = {"singlet_refractor", "achromat_doublet", "apo_triplet"}
