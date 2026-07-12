# FreeCAD MCP — third-party notice

The FreeCAD workbench / XML-RPC addon under `freecad_mcp/addon/` is
vendored from:

- Upstream: [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp)
- Pinned commit: `22a7d7b2c881779c0770029e4532be1e85c87ea1`
- License: MIT (see `LICENSE`)
- Copyright: 2025 Shirokuma (k tanaka) / neka-nat

The stdio MCP bridge that Cursor launches is **not** vendored here. Sci-Viz
runs the published PyPI package via `uvx freecad-mcp` (same project,
version family 0.1.x). That package talks to the addon over localhost
XML-RPC (default port 9875).

FreeCAD itself is LGPL-2.1+ and is never bundled — install separately
(`brew install --cask freecad` on macOS).
