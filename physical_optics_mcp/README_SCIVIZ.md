# physical_optics_mcp

Production scalar diffraction, Gaussian-beamlet, and polarization analysis
over MCP. The server uses the exact Prysm and Poke revisions pinned by this
repository; Zemax and CODE V are not required.

## Setup

```bash
cd sci-viz-mcp
./install.sh
.venv/bin/python scripts/generate_mcp_config.py \
  --servers physical_optics_mcp
```

The server writes under `output/physical_optics/` by default. Override this
with `PHYSICAL_OPTICS_OUTPUT_DIR`. Models are persistent JSON files; numeric
artifacts use NPZ/CSV/JSON and deterministic names derived from the model and
operation inputs.

## Units and model

| Quantity | Unit |
|---|---|
| pupil diameter and sample spacing | mm |
| wavelength | nm |
| wavefront/Zernike coefficient | nm OPD |
| field angle | deg |
| focus/free-space distance | mm |
| PSF and encircled-energy radius | µm |
| MTF spatial frequency | cycles/mm |
| Gaussian-beamlet internal calculation | SI, converted at the boundary |

The server-native `sciviz.physical_optics/v1` model stores a pupil,
weighted wavelengths, weighted fields, and normalized `(n,m)` Prysm Zernike
coefficients. Every mutating model tool writes JSON immediately.

## Tools

| Group | Tools |
|---|---|
| Environment | `physical_optics_health`, `physical_optics_reference` |
| Models | `physical_optics_new_model`, `physical_optics_load_model`, `physical_optics_save_model`, `physical_optics_list_models`, `physical_optics_get_model` |
| Definition | `physical_optics_define_pupil`, `physical_optics_define_wavelengths_fields`, `physical_optics_set_aberrations` |
| Scalar optics | `physical_optics_wavefront`, `physical_optics_propagate`, `physical_optics_psf`, `physical_optics_mtf`, `physical_optics_encircled_energy` |
| Beam/polarization | `physical_optics_gaussian_beamlets`, `physical_optics_polarization_jones` |
| Output | `physical_optics_render`, `physical_optics_export` |

`physical_optics_propagate` supports Prysm FFT focus and angular-spectrum
free-space propagation. PSFs are normalized to unit sampled energy. MTF uses
`prysm.otf.mtf_from_psf`.

## Example: diffraction-limited circular pupil

Call the tools in this order:

```json
{"name":"physical_optics_new_model","arguments":{"name":"flare-poc-pupil","model_id":"flare-poc-pupil"}}
{"name":"physical_optics_define_pupil","arguments":{"model_id":"flare-poc-pupil","shape":"circle","diameter_mm":25.0,"samples":512,"obscuration_ratio":0.0,"apodization":{"type":"uniform"}}}
{"name":"physical_optics_define_wavelengths_fields","arguments":{"model_id":"flare-poc-pupil","wavelengths":[{"value_nm":532.0,"weight":1.0}],"fields":[{"x_deg":0.0,"y_deg":0.0,"weight":1.0}]}}
{"name":"physical_optics_psf","arguments":{"model_id":"flare-poc-pupil","effective_focal_length_mm":100.0,"oversampling":4.0}}
{"name":"physical_optics_mtf","arguments":{"model_id":"flare-poc-pupil","effective_focal_length_mm":100.0,"frequencies_cycles_per_mm":[0,50,100]}}
{"name":"physical_optics_render","arguments":{"model_id":"flare-poc-pupil","kind":"psf","effective_focal_length_mm":100.0}}
```

At 550 nm and f/10, the analytic first Airy-zero radius is 6.71 µm and the
encircled energy there is approximately 0.838. The test suite checks both this
case and the analytic circular-pupil MTF.

## Example: Gaussian beamlets and Jones interfaces

```json
{"name":"physical_optics_gaussian_beamlets","arguments":{"model_id":"flare-poc-pupil","waist_mm":0.5,"nrays_across":9,"elements":[{"type":"free_space","distance_mm":50.0},{"type":"thin_lens","focal_length_mm":100.0},{"type":"free_space","distance_mm":100.0}],"grid_samples":128}}
```

This initializes the bundle with `poke.poke_core.Rayfront` and propagates its
complex curvature with `poke.beamlets.prop_complex_curvature`.

```json
{"name":"physical_optics_polarization_jones","arguments":{"wavelength_nm":532.0,"input_jones":[1.0,0.0],"interfaces":[{"n1":1.0,"n2":1.5,"incidence_angle_deg":45.0,"mode":"transmit","basis_rotation_deg":0.0}]}}
```

The Jones tool returns per-interface Fresnel coefficients, the system Jones
and Mueller matrices, and output Stokes parameters.

## FLARE Rev 2.2 PoC use

Use this server as an independent physics cross-check, not as a replacement
for FLARE's registered five-arm broadband forward model:

1. Create the hard-aperture branch with a 0.55 mm circular pupil,
   656.3 nm wavelength, and 200.2 mm EFL. Call PSF and encircled energy to
   verify the approximately 291.5 µm first-zero radius.
2. Create the Gaussian branch with `waist_mm:0.275` and a sequence containing
   200 mm free space, a 200.2 mm thin lens, and the registered detector
   distance. Use the returned beam radius only as the independent Gaussian
   envelope check.
3. Call Jones analysis for every registered PM-axis/analyzer branch and export
   Stokes/Jones results into the FLARE release evidence.
4. Run each of the 101 registered wavelengths independently if a Prysm
   cross-check is needed; apply FLARE's frozen rectangular-band photon weights
   and finite-pixel integration in the FLARE code.

The server-native pupil currently represents one circle or square. It does
not encode the five arbitrary Golomb marks, coherent `N²=25` sum, rectangular
passband integration, or IMX585 finite pixels. Those remain in
`models/poc_combiner/optics.py`, where the preregistered draw order and
convergence checks are enforced.

## Limitations and upstream behavior

- The pinned Prysm revision has PSF and OTF/MTF routines but no
  encircled-energy helper. The server therefore performs a deterministic
  radial cumulative sum of the normalized Prysm PSF; it does not fabricate an
  upstream API.
- Poke labels Gaussian beamlet decomposition experimental. This server exposes
  the tested first-order ABCD complex-curvature subset.
- Native polarization is a planar Fresnel-interface sequence with optional
  Jones-basis rotations. Arbitrary 3D coated-surface polarization ray tracing
  requires ray data from Poke's optional Zemax or CODE V adapters.
- `physical_optics_health` explicitly reports those commercial adapters as
  unavailable unless their Windows COM bindings are detected. All native
  tools remain usable without either application.

## Tests

```bash
MPLBACKEND=Agg .venv/bin/python -m pytest -q \
  tests/test_physical_optics_mcp.py
```

The suite covers model persistence, stdio MCP, Airy encircled energy,
circular-pupil MTF, aberrated Strehl, Gaussian propagation, Fresnel/Jones
coefficients, rendering, export, and deterministic regeneration.
