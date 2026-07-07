# PixInsight MCP in Sci-Viz

Vendored from [`aescaffre/pixinsight-mcp`](https://github.com/aescaffre/pixinsight-mcp)
at upstream commit `db5b1e2` under the MIT license. See
`THIRD_PARTY_NOTICE.md` and `LICENSE`.

This server lets an AI assistant control PixInsight for astrophotography
processing through PixInsight's PJSR scripting engine. PixInsight has no HTTP
or socket automation API, so the bridge uses file-based IPC:

## Licensing — read this first

This module is only a *bridge*. It does not include, replace, or license
the software it controls:

- **PixInsight** is commercial software. You need a valid PixInsight
  license from [pixinsight.com](https://pixinsight.com/) — every tool in
  this module executes inside a running PixInsight instance.
- **RC Astro plugins** — the sharpening, denoising, and star-removal
  workflows this module recommends and drives (BlurXTerminator,
  NoiseXTerminator, StarXTerminator) are commercial PixInsight plugins
  sold separately by [RC Astro](https://www.rc-astro.com/). Install and
  license them in PixInsight before using those workflows; without them
  the corresponding tool calls will fail inside PixInsight.
- The bridge code itself is MIT-licensed (vendored from
  `aescaffre/pixinsight-mcp`, see `THIRD_PARTY_NOTICE.md`).

```
Cursor / MCP client
  └─ stdio → pixinsight_mcp/build/index.js
       └─ writes JSON commands → ~/.pixinsight-mcp/bridge/commands/
PixInsight
  └─ pjsr/pixinsight-mcp-watcher.js polls commands, runs PJSR, writes results
       └─ ~/.pixinsight-mcp/bridge/results/
```

## Setup

```bash
cd <repo>/pixinsight_mcp
npm install
npm run build
npm run setup-bridge
```

Then, inside PixInsight, run:

```text
Script → Run Script…
pixinsight_mcp/pjsr/pixinsight-mcp-watcher.js
```

Keep that watcher running while MCP tools execute. Bridge latency is typically
around 2 seconds per tool call.

## Cursor MCP Registration

Example `~/.cursor/mcp.json` entry:

```json
{
  "mcpServers": {
    "pixinsight": {
      "command": "node",
      "args": [
        "<repo>/pixinsight_mcp/build/index.js"
      ],
      "cwd": "<repo>/pixinsight_mcp"
    }
  }
}
```

## Tools

Core image/session tools:

- `list_open_images`
- `open_image`
- `save_image`
- `close_image`
- `get_image_statistics`

Processing tools:

- `run_pixelmath`
- `remove_gradient`
- `color_calibrate`
- `remove_green_cast`
- `stretch_image`
- `apply_curves`
- `denoise`
- `sharpen`
- `deconvolve`
- `combine_lrgb`
- `blend_narrowband`

Knowledge helper:

- `search_processing_recommendations`

## Notes

- `node_modules/` and `build/` are intentionally ignored. Rebuild locally with
  `npm install && npm run build`.
- Upstream docs are copied in `docs/`; the original README is
  `UPSTREAM_README.md`.
- This module controls PixInsight processes and files directly. Prefer working
  on duplicate/copy images until a workflow is proven.
