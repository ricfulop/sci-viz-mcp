# Ray Optics MCP — Telescope Design Manual

AI-driven 2D geometric optics for collaborative telescope design, built on the
[ray-optics simulation engine](https://github.com/ricktu288/ray-optics)
(ricktu288, Apache-2.0). The engine is vendored (`vendor/rayOptics.js` +
`vendor/runner.js`) and executed headlessly via Node.js; scenes use the same
JSON format as the [web app](https://phydemo.app/ray-optics/simulator/), so
anything built here can be opened and hand-edited there and vice versa.

```
Cursor chat ──MCP/stdio──▶ ray_optics_mcp_server.py
                                 │  scene JSON
                                 ▼
                           node vendor/runner.js ──▶ rayOptics.js (headless)
                                 │
                                 ▼
                    detector readings + PNG renders (node-canvas)
```

---

## 1. Setup

Registered in `~/.cursor/mcp.json` as `ray_optics_mcp`. Requirements:

- Node.js ≥ 18 (discovered automatically; override with `RAY_OPTICS_NODE`)
- `vendor/` contains the `dist-integrations` build of ray-optics
  (`rayOptics.js` + `runner.js`). `node_modules` (node-canvas) is not in git —
  run `npm install` inside `vendor/` once per machine.
- Python 3.10+ (stdlib only — no pip dependencies)

After editing any server code, **toggle the server off/on in Cursor's MCP
settings** — the running process does not hot-reload.

Smoke tests:

```bash
cd ray_optics_mcp
python3 validate_designs.py   # traces all 18 presets through the engine
python3 test_e2e.py           # full MCP JSON-RPC round-trip incl. renders
```

## 2. Conventions

| Convention | Value |
|---|---|
| Coordinates | **y points down**; scene viewport ≈ 1500 × 900 units |
| Units | Arbitrary (treat as mm for telescope-scale sanity) |
| Light direction | Presets launch parallel beams traveling **+x** |
| Surface radii | Standard sign convention: R > 0 → center of curvature to the right |
| Detector sign | Detectors are oriented so focused (converging) light reads **positive** power; a beam crossing the detector plane backwards reads negative and is filtered out of spot statistics |
| Wavelengths | nm; chromatic scenes use RGB = 473 / 540 / 635 nm |

## 3. Tool reference (14 tools)

### Scene management

| Tool | Description |
|---|---|
| `ray_optics_new_scene` | Create an empty scene (name, width, height, ray density) |
| `ray_optics_load_scene` | Load a scene JSON file (web-app compatible) |
| `ray_optics_save_scene` | Persist a scene to a JSON file |
| `ray_optics_get_scene` | Return the full scene JSON |
| `ray_optics_list_scenes` | List scenes held by the server |
| `ray_optics_list_objects` | Enumerate objects with index, type, name |

### Scene editing

| Tool | Description |
|---|---|
| `ray_optics_add_objects` | Append raw objects (any engine type: `Beam`, `Mirror`, `ParamMirror`, `Glass`, `ParamGlass`, `IdealLens`, `Detector`, `TextLabel`, …) |
| `ray_optics_update_object` | Patch fields of an object by index (e.g. change a focal length, move a detector) |
| `ray_optics_remove_objects` | Delete objects by index list |
| `ray_optics_set_scene_settings` | Ray density, `simulateColors`, viewport, etc. |

### Simulation & rendering

| Tool | Description |
|---|---|
| `ray_optics_simulate` | Run the engine, return detector readings (power, irradiance map, bin positions) without rendering |
| `ray_optics_render` | Render a PNG (auto-framed or explicit region), return image path + detector readings |
| `ray_optics_make_telescope` | Build a parametric telescope preset (§4) |
| `ray_optics_reference` | Return the engine's own docs (`objects`, `modules`, `integrations`, `instructions`) |

Renders also stream to the live preview dashboard (`preview/`) at
[http://localhost:8765](http://localhost:8765).

## 4. Telescope preset library (18 designs)

All presets accept `params` (every field optional). Common parameters:

| Parameter | Meaning |
|---|---|
| `aperture` | Clear aperture D |
| `field_angle_deg` | Tilts the incoming beam to show off-axis aberrations (coma, field curvature) |
| `chromatic` | Adds RGB wavelengths + `simulateColors` (default **on** for `singlet_refractor`, `achromat_doublet`, `apo_triplet`) |
| `ray_density` | Scene ray density (default 0.3) |
| `axis_y`, `vertex_x` / `objective_x`, `source_x` | Layout placement |

`design_info` in the response always includes focus position(s), f-ratio, and
for auto-tuned designs the tuned parameter values and traced RMS spot radius.

### 4.1 Reflectors

| Design | Defaults | Prescription |
|---|---|---|
| `newtonian` | D=200, f=800 (f/4) | Parabolic primary (K=−1) + flat fold; `focal_length`, `focus_offset` |
| `prime_focus` | D=200, f=800 | Bare parabola, detector at prime focus |
| `herschelian` | D=180, f=900 | Off-axis segment of a parent parabola, unobstructed; `off_axis_offset` (default 0.75·D, must exceed D/2+20) |
| `cassegrain` | D=240, f1=600, d=450, b=120 | Classical: K1=−1, K2=−((m+1)/(m−1))² exact confocal hyperbola |
| `ritchey_chretien` | same layout | Aplanatic: K1=−1−(2/m³)(q/d), K2=−1−[2/(m−1)³]·[m(2m−1)+q/d] — coma-free |
| `dall_kirkham` | same layout | Elliptical primary K1=−1+k(m−1)(m+1)²/m³, **spherical** secondary K2=0 |
| `gregorian` | D=200, f1=500, d=1.25·f1 | Parabola + confocal **ellipse** beyond prime focus; erect image; needs `secondary_distance > primary_focal_length` |
| `nasmyth` | Cassegrain layout + `tertiary_offset`=0.3·f1 | Flat 45° tertiary folds to a side (platform) focus |

Two-mirror geometry: `p = f1 − d`, `q = d + b`, magnification `m = q/p`,
system focal length `f_sys = m·f1`, convex secondary vertex radius
`R2 = 2pq/(q−p)`. The primary hole radius and secondary edge are sized
automatically from the marginal ray cone. Try
`{"design": "cassegrain", "params": {"field_angle_deg": 0.75}}` vs the same
on `ritchey_chretien` to see the RC's coma advantage in the traced spot.

### 4.2 Catadioptrics (engine-in-the-loop auto-tuned)

| Design | Defaults | What is tuned |
|---|---|---|
| `schmidt_camera` | D=200, f=400 (f/2) | Full-aperture aspheric corrector z(y) = s·(y⁴ − 1.5·h²y²) at the center of curvature of a **spherical** mirror. Corrector strength `s` tuned by golden-section search on the traced RMS spot (theory value s₀ = 1/[32(n−1)f³] used to bracket the search). Info reports corrected vs uncorrected RMS. |
| `schmidt_cassegrain` | D=200, f1=400, d=310, b=150 | Both mirrors spherical; Schmidt corrector strength tuned the same way. The corrector's neutral-zone r² term adds weak paraxial power, so the detector tracks the traced focus at every trial strength. |
| `maksutov_cassegrain` | D=150, f1=4.3·D, meniscus at 3.2·D, t=0.09·D | Gregory (spot) Maksutov: deep BK7 meniscus with the achromatic constraint R2 = R1 − t(n²−1)/n², secondary = aluminized spot on the meniscus rear. Meniscus R1 tuned by ray tracing; geometry guard rejects layouts whose focus lands inside the tube. |

### 4.3 Refractors

| Design | Defaults | Notes |
|---|---|---|
| `keplerian_refractor` | D=160, f_obj=700, f_eye=100 | Ideal thin lenses; afocal exit beam, mag = f_obj/f_eye |
| `galilean_refractor` | same | Negative eyepiece before the internal focus; erect image |
| `singlet_refractor` | D=120, f=600 | Real equiconvex BK7 lens — chromatic-aberration demo (RGB defaults on) |
| `achromat_doublet` | D=120, f=600 | Fraunhofer BK7+F2 cemented-style pair; powers from the achromat condition φᵢ ∝ Vᵢ/(V₁−V₂) |
| `petzval_refractor` | D=110, f_front=500, f_rear=450, sep=300 | Two air-spaced achromat groups; fast astrograph (~f/3) |
| `apo_triplet` | D=140, f=700 (f/5) | FPL53/F2/FPL53 air-spaced ED triplet. Achromat power split against the ED glass; ED power divided across the outer elements; **all three element bendings auto-tuned** by coordinate descent (2 sweeps × golden section) on the 90 %-energy clipped spot. Holds a diffraction-floor spot at f-ratios where the doublet shows spherical aberration (f/4: doublet 0.153 vs triplet 0.125 bins). |
| `flatfield_petzval` | D=110, groups as petzval, `elements`=5, `design_field_deg`=3 | Flat-field astrograph. `elements: 4` (quadruplet) tunes the group separation; `elements: 5` (quintuplet) adds a plano-concave F2 field flattener `flattener_distance` (default 14) before focus and tunes its focal length. The tuning metric traces a 0° **and** a design-field beam onto the *same flat focal plane* and minimizes the combined clipped RMS — a true field-flatness optimization. Scene renders at the design field angle by default; pass `field_angle_deg: 0` for the on-axis view. |

### 4.4 Glass catalog (two-term Cauchy: n(λ) = A + B/λ²)

| Glass | A | B (µm²) | n_d | V_d | Role |
|---|---|---|---|---|---|
| BK7 | 1.5046 | 0.00420 | 1.5168 | 64.2 | Crown |
| F2 | 1.5942 | 0.00892 | 1.6200 | 36.4 | Flint |
| FPL53 | 1.4317 | 0.00242 | 1.4388 | 94.9 | ED (fluorite-like) |

**Dispersion-model caveat (important for honest comparisons):** with only two
Cauchy terms, any two-glass achromat cancels color *exactly at all
wavelengths* — secondary spectrum does not exist in this engine. The ED
triplet's measurable advantage here is therefore monochromatic (spherical
aberration control at fast f-ratios), not chromatic. Design-info notes state
this explicitly.

## 5. Measuring image quality

`ray_optics_simulate` returns, per detector:

- `power` — total flux through the segment (signed by crossing direction)
- `irradianceMap` + `binPositions` — 1D irradiance histogram along the segment

`telescope_designs.py` provides the analysis helpers used by the auto-tuners:

| Helper | Definition |
|---|---|
| `spot_stats(map, pos)` | Flux-weighted centroid and RMS half-width. Negative bins (backward-crossing light, e.g. the incoming beam grazing the detector plane) are clipped to zero first. |
| `clipped_spot_rms(map, pos, frac=0.9)` | RMS of the minimal contiguous bin window around the peak containing 90 % of the positive energy. Use this to compare *good* designs — the full-map RMS is dominated by faint scattered-light wings and saturates. |
| `_rms_spot(objs, clip=None)` | Convenience: run the scene headlessly, return the chosen statistic. |

Rule of thumb: full-map RMS for coarse pass/fail, clipped RMS for
discriminating between well-corrected designs. Values are in scene units;
the resolution floor is set by the detector bin size
(`2 × half-width / bins`).

## 6. How the auto-tuning works

Catadioptrics and the two new refractors are tuned **empirically** — the
engine itself is the merit function, which sidesteps sign-convention and
higher-order-term errors in analytic formulas:

1. Build the scene as a function of the free parameter(s); the detector is
   re-placed at the *traced paraxial focus* for every trial (a paraxial
   ray tracer `_trace` handles mirror/refraction/gap sequences on an
   unfolded axis).
2. Evaluate the spot statistic via a headless engine run (~0.3 s per run).
3. Minimize: golden-section search for 1 parameter
   (Schmidt strength, Maksutov R1, flattener power, Petzval separation);
   coordinate descent over golden-section line searches for several
   (apo triplet bendings). Geometry violations return a large penalty.
4. For the flat-field Petzval the merit is multi-configuration:
   √(mean of squared clipped RMS at 0° and at the design field), both on one
   fixed flat detector plane.

Typical build times: Schmidt/Maksutov ~2–3 s, flat-field Petzval ~5 s,
apo triplet ~10 s.

## 7. Worked examples

Build, inspect, render:

```jsonc
// 1. build
ray_optics_make_telescope {"design": "ritchey_chretien",
                           "params": {"aperture": 240, "primary_focal_length": 600,
                                      "secondary_distance": 450,
                                      "back_focal_distance": 120}}
// -> scene_id "ritchey-chretien-1", design_info with K1/K2, f/9.5

// 2. quantify
ray_optics_simulate {"scene_id": "ritchey-chretien-1"}
// -> focal_plane power, irradiance map

// 3. look
ray_optics_render {"scene_id": "ritchey-chretien-1", "image_width": 1400}
```

Off-axis comparison (coma):

```jsonc
ray_optics_make_telescope {"design": "cassegrain",       "params": {"field_angle_deg": 0.75}}
ray_optics_make_telescope {"design": "ritchey_chretien", "params": {"field_angle_deg": 0.75}}
// compare RMS from the two irradiance maps
```

Chromatic demo:

```jsonc
ray_optics_make_telescope {"design": "singlet_refractor"}   // RGB spread at focus
ray_optics_make_telescope {"design": "achromat_doublet"}    // collapsed to one focus
```

Flat-field astrograph, both variants:

```jsonc
ray_optics_make_telescope {"design": "flatfield_petzval", "params": {"elements": 4}}
ray_optics_make_telescope {"design": "flatfield_petzval", "params": {"elements": 5, "design_field_deg": 4}}
// design_info reports rms_spot_on_axis_90pct, rms_spot_at_field_90pct,
// and (quintuplet) rms_at_field_without_flattener_90pct
```

Hand-editing a preset: presets are ordinary scenes. Use
`ray_optics_list_objects` to find an element's index, then
`ray_optics_update_object` to move a detector, change an `IdealLens`
`focalLength`, retilt a fold mirror, etc., and re-simulate.

## 8. Engine gotchas (hard-won)

| Gotcha | Consequence | Rule |
|---|---|---|
| Scientific notation in equation strings | `1e-10` parses as *1·e − 10* (Euler's e) in the engine's math parser — silently wrong optics | All numbers in `ParamMirror`/`ParamGlass` equations go through `_num()` (fixed-point formatting) |
| One `ParamMirror` with disjoint pieces | Annular mirrors (primary with a hole) must be **separate objects** per span; pieces of one object must form a continuous curve | `_conic_mirror` returns a *list*; splice with `objs += ...`, never `append` |
| Detector orientation | Power is signed by crossing direction | `_detector(..., direction)` orients the segment so the design's converging beam reads positive |
| Incoming beam crossing the detector plane | Adds a huge uniform negative pedestal to the irradiance map | `spot_stats` clips negative bins |
| Corrector aspheric term scale | Schmidt strength ~1e-10 in scene units | Bracket searches on the theory value s₀, never on unit-scale guesses |
| Stale MCP process | Edits to server/builders don't take effect | Toggle the MCP server in Cursor settings after code changes |

## 9. Extending the preset library

New designs live in `telescope_designs.py`:

1. Write `build_<name>(p) -> (objs, info)` using the helpers:
   `_beams`, `_conic_mirror`, `_annular_spans`, `_lens`, `_element_lens`,
   `_corrector_plate`, `_detector`, `_label`, `_achromat_surfaces`,
   `_refractor_focus`, `_trace` / `_focus_distance`.
2. If the design has a free parameter without a robust closed form, tune it:
   wrap the scene build in a metric (`_spot_or_bad(objs, clip=0.9)`) and
   minimize with `_golden_min`.
3. Register in `BUILDERS`; add to `CHROMATIC_DEFAULT` if it should trace RGB
   by default.
4. Add the name to the `ray_optics_make_telescope` enum + description in
   `ray_optics_mcp_server.py`.
5. Add a case to `validate_designs.py`, run it, and render for visual
   inspection. Extend `test_e2e.py` if the design exercises a new code path.

## 10. File map

| File | Role |
|---|---|
| `ray_optics_mcp_server.py` | MCP JSON-RPC server, tool schemas, scene store |
| `engine.py` | Node.js discovery + headless `run_scene()` |
| `telescope_designs.py` | All 18 preset builders, paraxial tracer, spot metrics, auto-tuners |
| `validate_designs.py` | Traces every preset; power/RMS report |
| `test_e2e.py` | Full MCP round-trip test (build → simulate → render → edit) |
| `knowledge/` | Engine reference docs served by `ray_optics_reference` |
| `vendor/` | Vendored ray-optics engine + runner + node-canvas |
