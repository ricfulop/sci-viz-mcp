# Siril MCP in Sci-Viz

An MCP server that lets an AI assistant drive [Siril](https://siril.org)
for astrophotography processing — the free/open-source counterpart to
`pixinsight_mcp`, following the same workflow shape:

```
stack → open → statistics → remove gradient → color calibrate →
[deconvolve] → stretch → remove green → denoise → export
```

Written for Sci-Viz (not vendored). At the time of writing the only other
Siril MCP is [`taco-ops/siril-mcp`](https://github.com/taco-ops/siril-mcp),
an early-stage project scoped to Seestar mosaic scripts; this module instead
exposes Siril's general processing and stacking commands as chainable tools.

## Licensing

Siril is **free software (GPLv3)** — unlike PixInsight, no commercial
license is needed for any tool in this module. Optional extras:

- **StarNet** star removal (`starnet` via `siril_run_commands`) requires the
  free StarNet weights installed in Siril's preferences.
- `siril_color_calibrate` with `spcc`/`pcc` downloads Gaia catalog data, so
  it needs internet access on first use.

## How it works

Siril ships first-class headless automation, so there is no watcher or
file-IPC bridge (the hack `pixinsight_mcp` needs). Each tool call:

1. generates a Siril script (`.ssf`) — `load` → commands → `save`,
2. runs it with `siril-cli -d <workdir> -s <script>`,
3. tracks the output FITS in a session, so calls chain.

Originals are never modified; every session works on a FITS copy under
`output/siril/<session_id>/`, and every op appends a suffix
(`_bkg`, `_stretch`, ...) so intermediate states are preserved.

## Requirements

- [Siril](https://siril.org) ≥ 1.2 (tested on 1.4.4). On macOS the binary is
  auto-detected at `/Applications/Siril.app/Contents/MacOS/siril-cli`;
  otherwise set `SIRIL_CLI=/path/to/siril-cli`.
- Python ≥ 3.10, no extra Python dependencies.

## Tools

Setup and session:

- `siril_check` — locate siril-cli, report version
- `siril_open_image` — open FITS/TIFF/PNG/JPG/RAW into a session
- `siril_list_sessions`
- `siril_get_statistics` — per-channel mean/median/sigma/bgnoise

Processing (PixInsight-workflow mirror):

| tool | Siril command | PixInsight equivalent |
|---|---|---|
| `siril_remove_gradient` | `subsky` (RBF or poly) | AutomaticBackgroundExtractor |
| `siril_color_calibrate` | `platesolve` + `spcc`/`pcc` | SPCC / PCC |
| `siril_deconvolve` | `makepsf stars` + `rl`/`wiener` | BlurXTerminator (sharpening) |
| `siril_stretch` | `autostretch` / `asinh` / `autoght` | STF + HistogramTransformation |
| `siril_remove_green` | `rmgreen` | SCNR |
| `siril_denoise` | `denoise` (NL-Bayes) | NoiseXTerminator |
| `siril_crop` | `crop` | DynamicCrop |
| `siril_run_commands` | any script command | — |

Stacking (beyond what the PixInsight bridge covers):

- `siril_preprocess_stack` — convert, calibrate (darks/flats/biases),
  debayer (OSC), register, sigma-clip stack; opens the result as a session.

Export and knowledge:

- `siril_save_image` — png/jpg/tif/fit; raster exports carry the Sci-Viz
  attribution stamp
- `siril_workflow` — recommended processing order with PixInsight mapping

## Cursor MCP registration

Generated automatically by `scripts/generate_mcp_config.py`, or manually:

```json
{
  "mcpServers": {
    "siril_mcp": {
      "command": "<repo>/.venv/bin/python",
      "args": ["<repo>/siril_mcp/siril_mcp_server.py"],
      "cwd": "<repo>",
      "transport": "stdio"
    }
  }
}
```

## Environment variables

| variable | default | purpose |
|---|---|---|
| `SIRIL_CLI` | auto-detect | path to the siril-cli binary |
| `SIRIL_MCP_OUTPUT_DIR` | `<repo>/output/siril` | session working files |
| `SIRIL_MCP_TIMEOUT_S` | 900 | per-script timeout (stacking overrides to 3600) |

## Common failures

- `siril-cli not found` — install Siril or set `SIRIL_CLI`.
- `spcc`/`pcc` fails — image lacks WCS/coordinates in the FITS header or has
  too few stars; plate solving also needs internet for catalog download.
- `denoise` reports `no suitable data` — image is likely already stretched
  or nearly flat; denoise works best on linear stacked data.
- `starnet` fails via `siril_run_commands` — install StarNet weights in
  Siril preferences first.
