# optical_design_mcp

Persistent sequential optical prescriptions, ray tracing, analysis,
optimization, and tolerancing over MCP, backed by the optional
`optiland==0.6.0` dependency.

## Setup

```bash
cd sci-viz-mcp
./install.sh --with-design
.venv/bin/python scripts/generate_mcp_config.py \
  --servers optical_design_mcp
```

The server still starts if Optiland is absent. Model lifecycle and editing
remain available; engine-backed tools return a structured
`ENGINE_UNAVAILABLE` error with the install command.

Outputs default to `output/optical_design/`. Override with
`OPTICAL_DESIGN_OUTPUT_DIR`.

## Units and prescription semantics

| Quantity | Unit |
|---|---|
| radius, thickness, aperture EPD, ray intercept, spot radius | mm |
| angular field | deg |
| object/image-height field | mm |
| wavelength at the MCP boundary | nm |
| Optiland internal wavelength | µm |
| spatial frequency | cycles/mm |
| normalized ray coordinates `Hx`, `Hy`, `Px`, `Py` | dimensionless |
| conic | dimensionless |

The first surface is the object and the last is the image. Interior surface
`material` is the medium after that surface. `radius_mm: null` means planar;
`thickness_mm: null` is reserved for an object at infinity. The server stores
`sciviz.optical_design/v1` JSON and reconstructs an Optiland `Optic` for each
analysis, so saved prescriptions remain explicit and reviewable.

## Tools

| Group | Tools |
|---|---|
| Environment | `optical_design_health`, `optical_design_reference` |
| Models | `optical_design_new_model`, `optical_design_load_model`, `optical_design_save_model`, `optical_design_list_models`, `optical_design_get_model` |
| Prescription | `optical_design_add_surface`, `optical_design_update_surface`, `optical_design_remove_surface`, `optical_design_set_aperture_stop`, `optical_design_set_fields`, `optical_design_set_wavelengths` |
| Glass | `optical_design_materials` |
| Analysis | `optical_design_trace`, `optical_design_spot`, `optical_design_mtf` |
| Design | `optical_design_optimize`, `optical_design_tolerance` |
| Output | `optical_design_render`, `optical_design_export` |

Supported dedicated surface types are `standard`, `plane`, `even_asphere`,
`odd_asphere`, and `paraxial`. Advanced Optiland geometry keywords can be
passed through the surface `parameters` object, but not every freeform
parameter has a dedicated update field.

## Example: create and analyze a singlet

```json
{"name":"optical_design_new_model","arguments":{"name":"flare-imaging-singlet","model_id":"flare-imaging-singlet","preset":"biconvex_singlet"}}
{"name":"optical_design_set_aperture_stop","arguments":{"model_id":"flare-imaging-singlet","aperture_type":"EPD","value":10.0,"stop_index":1}}
{"name":"optical_design_set_fields","arguments":{"model_id":"flare-imaging-singlet","field_type":"angle","fields":[{"x_deg":0.0,"y_deg":0.0},{"x_deg":0.0,"y_deg":2.0}]}}
{"name":"optical_design_set_wavelengths","arguments":{"model_id":"flare-imaging-singlet","wavelengths":[{"value_nm":486.1,"weight":1.0},{"value_nm":587.6,"weight":1.0},{"value_nm":656.3,"weight":1.0}],"primary_index":1}}
{"name":"optical_design_trace","arguments":{"model_id":"flare-imaging-singlet","Hx":0.0,"Hy":0.0,"wavelength_nm":587.6,"num_rays":32,"distribution":"uniform"}}
{"name":"optical_design_spot","arguments":{"model_id":"flare-imaging-singlet","num_rings":8,"reference":"chief_ray"}}
{"name":"optical_design_mtf","arguments":{"model_id":"flare-imaging-singlet","method":"geometric","num_rays":64,"num_points":256}}
{"name":"optical_design_render","arguments":{"model_id":"flare-imaging-singlet","kind":"layout","num_rays":5}}
```

For a custom FLARE prescription, start with `preset:"empty"` and insert
surfaces before the image:

```json
{"name":"optical_design_add_surface","arguments":{"model_id":"flare-custom","surface":{"surface_type":"standard","radius_mm":50.0,"thickness_mm":5.0,"material":"N-BK7","is_stop":true,"comment":"front"}}}
```

Use `optical_design_materials` to search or exactly validate glass names
before assigning them.

## FLARE Rev 2.2 PoC use

Build an independent AC254-200-A sequential model from the frozen
prescription:

1. `optical_design_new_model` with `preset:"empty"`.
2. Insert R1 at `+77.4 mm`, `thickness_mm:4.0`,
   `material:"N-SSK5"`, and `is_stop:true`.
3. Insert R2 at `-87.6 mm`, `thickness_mm:2.5`, and
   `material:"LAFN7"`.
4. Insert R3 at `+291.1 mm`, `thickness_mm:194.0`, and
   `material:"air"`.
5. Set EPD to the conservative 22.86 mm clear aperture, fields to the
   registered angular checks, and wavelengths to the 656.3 nm passband grid.
6. Call trace/spot/MTF for nominal and detector-focus branches; use seeded
   tolerance only for lens prescription variables and registered absolute
   values.

Do not use Optiland's random tolerance run to replace FLARE's 50,000-sample
assembly analysis. FLARE freezes a seven-block PCG64 draw order spanning fiber
positions, axial offsets, two-axis tilts, lens distance, detector defocus, and
temperature. Preserve that exact analysis in
`models/poc_combiner/tolerances.py`; use this server for independent lens
prescription and aberration evidence. The existing `ray_optics_mcp` remains
the geometric five-beam packaging/clearance model.

## Optimization

Optimization uses Optiland `OptimizationProblem` and deterministic SciPy
`OptimizerGeneric` methods. The optimized common prescription values are
written back to the persistent model.

```json
{"name":"optical_design_optimize","arguments":{"model_id":"flare-imaging-singlet","variables":[{"type":"radius","surface_number":2,"min":-100.0,"max":-20.0}],"operands":[{"type":"rms_spot_size","target":0.0,"input_data":{"surface_number":-1,"Hx":0.0,"Hy":0.0,"num_rays":8,"wavelength_nm":587.6,"distribution":"uniform"}}],"method":"L-BFGS-B","max_iterations":100,"tolerance":1e-6}}
```

Variables named `radius` or `thickness` use mm; `conic` is dimensionless;
tilt follows Optiland's radians convention; index is dimensionless.

## Seeded tolerancing

`optical_design_tolerance` uses Optiland `Tolerancing`,
`DistributionSampler`, and `MonteCarlo`. Each perturbation gets
`seed + perturbation_index`. Optiland samplers set the variable to the sampled
absolute value, so a radius perturbation with `mean:50, sigma:0.1` means a
50 mm nominal radius with 0.1 mm standard deviation, not a zero-centered
delta. Radius/thickness samples are mm; conic/index samples are dimensionless.

```json
{"name":"optical_design_tolerance","arguments":{"model_id":"flare-imaging-singlet","seed":20260711,"iterations":1000,"perturbations":[{"type":"radius","surface_number":1,"distribution":"normal","mean":50.0,"sigma":0.1}],"operands":[{"type":"rms_spot_size","input_data":{"surface_number":-1,"Hx":0.0,"Hy":0.0,"num_rays":8,"wavelength_nm":587.6,"distribution":"uniform"}}]}}
```

The server resets the Optiland object to nominal after the run and writes
deterministic CSV with mean, standard deviation, range, and quantiles.

## Export and limitations

`optical_design_export` supports server-native JSON, Optiland-native JSON,
prescription CSV, and result-artifact copy. Renders are APS-styled, carry
Sci-Viz attribution, and notify the live-preview dashboard.

The server does not require Zemax or CODE V. Optiland includes file converters
upstream, but this MCP intentionally uses its own explicit-unit schema as the
persistent source of truth. Only deterministic local optimizers are exposed.

## Tests

```bash
MPLBACKEND=Agg .venv/bin/python -m pytest -q \
  tests/test_optical_design_mcp.py
```

The suite covers the thick-lens Lensmaker focal length, on-axis symmetry,
spot and MTF invariants, CRUD persistence, glass search, optimization,
seeded tolerance regeneration, rendering/export, optional-dependency
degradation, and stdio MCP.
