# Third-Party Notices

sci-viz-mcp is built on, vendors, or drives the software below. Vendored
code keeps its original license file in its subdirectory. Commercial
applications are **not** distributed with this repo — you need your own
licenses for them.

## Vendored source code

| Component | Where | Upstream | License |
|-----------|-------|----------|---------|
| ray-optics simulation engine (`rayOptics.js`, `runner.js`) | `ray_optics_mcp/vendor/` | [ricktu288/ray-optics](https://github.com/ricktu288/ray-optics) (`dist-integrations` branch) | Apache-2.0 (`ray_optics_mcp/vendor/LICENSE`) |
| PixInsight MCP bridge (TypeScript server + PJSR watcher) | `pixinsight_mcp/` | [aescaffre/pixinsight-mcp](https://github.com/aescaffre/pixinsight-mcp) @ `db5b1e2` | MIT (`pixinsight_mcp/LICENSE`, see `pixinsight_mcp/THIRD_PARTY_NOTICE.md`) |
| FreeCADMCP workbench / XML-RPC addon | `freecad_mcp/addon/` | [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) @ `22a7d7b` | MIT (`freecad_mcp/LICENSE`, see `freecad_mcp/THIRD_PARTY_NOTICE.md`) |
| COMSOL execution MCP | `comsol_mcp/` | Flash-Physics-Twin project (internal), generalized here | Same terms as this repo |

## Open-source libraries this repo depends on

| Library | Used by | License |
|---------|---------|---------|
| [ASE](https://wiki.fysik.dtu.dk/ase/) | crystal_mcp, Blender add-on | LGPL-2.1+ |
| [pymatgen](https://pymatgen.org/) | crystal_mcp | MIT |
| [spglib](https://spglib.readthedocs.io/) | crystal_mcp (symmetry) | BSD-3-Clause |
| [matplotlib](https://matplotlib.org/) | all figure rendering, styles.py | matplotlib license (BSD-style) |
| [NumPy](https://numpy.org/) | everywhere | BSD-3-Clause |
| [h5py](https://www.h5py.org/) | comsol_mcp, comsol_viz_mcp | BSD-3-Clause |
| [mph](https://mph.readthedocs.io/) | comsol_mcp (COMSOL Java bridge) | MIT |
| [PyYAML](https://pyyaml.org/) | comsol_mcp inputs | MIT |
| [aiohttp](https://docs.aiohttp.org/) | live preview dashboard | Apache-2.0 |
| [OVITO Python module](https://www.ovito.org/) | ovito_mcp | OVITO Basic components GPL-3.0/MIT dual; the `ovito` pip package is free of charge — see ovito.org for terms |
| [node-canvas](https://github.com/Automattic/node-canvas) | ray_optics_mcp headless rendering | MIT |
| [Node.js](https://nodejs.org/) | ray_optics_mcp, pixinsight_mcp | MIT-style |
| [Blender](https://www.blender.org/) + [Blender Foundation MCP server](https://www.blender.org/lab/mcp-server/) | 3D rendering path | GPL-2.0+ (Blender); Foundation MCP server per its repo |
| [FreeCAD](https://www.freecad.org/) + [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) (`uvx freecad-mcp`) | CAD / TechDraw path | LGPL-2.1+ (FreeCAD); MIT (MCP bridge, not vendored — launched via uvx) |
| [Pillow](https://python-pillow.org/) | attribution stamping (optional) | MIT-CMU (HPND) |
| [Siril](https://siril.org/) | siril_mcp (driven via `siril-cli`, never bundled) | GPL-3.0 — free software, no paid license needed |
| [Prysm](https://github.com/brandondube/prysm) | `physical_optics_mcp` scalar diffraction, wavefront propagation, PSF, and MTF | MIT |
| [Poke](https://github.com/Jashcraf/poke) | `physical_optics_mcp` Gaussian beamlets and Fresnel/Jones polarization | BSD-3-Clause |
| [Astropy](https://www.astropy.org/) | optional units, FITS, WCS, coordinates, and time support | BSD-3-Clause |
| [POPPY](https://github.com/spacetelescope/poppy) | optional astronomical Fresnel/Fraunhofer propagation and PSFs | BSD-3-Clause |
| [AOtools](https://github.com/AOtools/aotools) | optional adaptive-optics propagation, turbulence, and wavefront analysis | LGPL-3.0 |
| [HCIPy](https://github.com/ehpor/hcipy) | optional atmospheric, adaptive-optics, polarization, and coronagraph simulation | MIT |
| [Optiland](https://github.com/optiland/optiland) | optional `optical_design_mcp` sequential design, ray tracing, optimization, and tolerancing | MIT |
| [PicoGK](https://github.com/leap71/PicoGK) 2.2 | picogk_mcp geometry kernel and native runtime | Apache-2.0 |
| [.NET](https://dotnet.microsoft.com/) 9 | picogk_mcp compiler and job runtime | MIT |
| [LEAP71 ShapeKernel](https://github.com/leap71/LEAP71_ShapeKernel) | picogk_mcp optional source module | Apache-2.0 |
| [LEAP71 LatticeLibrary](https://github.com/leap71/LEAP71_LatticeLibrary) | picogk_mcp optional source module | Apache-2.0 |
| [LEAP71 QuasiCrystals](https://github.com/leap71/LEAP71_QuasiCrystals) | picogk_mcp optional source module | Apache-2.0 |
| [LEAP71 RoverWheel](https://github.com/leap71/LEAP71_RoverWheel) | picogk_mcp optional source module | Apache-2.0 |
| [LEAP71 HelixHeatX](https://github.com/leap71/LEAP71_HelixHeatX) | picogk_mcp optional source module | Apache-2.0 |
| [PicoGK Examples](https://github.com/leap71/PicoGK_Examples) | picogk_mcp optional example source | CC0-1.0 |

The source-only LEAP 71 repositories are not vendored. Their exact commits
are fetched into a user cache according to `picogk_mcp/stack.lock.json`.
`PicoGK_SimulationExample` has no declared repository license as of the
locked revision, so Sci-Viz requires explicit opt-in before fetching it and
does not redistribute its source.

## Commercial software you must license yourself

These applications are controlled by sci-viz-mcp but never bundled:

| Application | Needed for | Licensing |
|-------------|-----------|-----------|
| **COMSOL Multiphysics** (6.x) | `comsol_mcp` solver tools (open model, mesh, run studies). Visualization of exported fields via `comsol_viz_mcp` works without it. | Commercial license from [comsol.com](https://www.comsol.com/) |
| **PixInsight** | All `pixinsight_mcp` tools — the bridge runs *inside* PixInsight via its PJSR scripting engine. | Commercial license from [pixinsight.com](https://pixinsight.com/) |
| **RC Astro plugins** (BlurXTerminator, NoiseXTerminator, StarXTerminator) | The deconvolution/denoise/star-removal workflows that `pixinsight_mcp` recommends and drives assume these are installed in PixInsight. | Each sold separately by [RC Astro](https://www.rc-astro.com/) |
| **Zemax OpticStudio** | Optional Poke ZOS-API adapter only. No native `physical_optics_mcp` tool requires it; health reports the adapter unavailable when absent. | Commercial license from Ansys |
| **CODE V** | Optional Poke CODE V adapter only. No native `physical_optics_mcp` tool requires it; health reports the adapter unavailable when absent. | Commercial license from Synopsys |

## Data / knowledge sources

- Ray-optics object/scene documentation in `ray_optics_mcp/knowledge/` is
  copied from the upstream ray-optics `ai-tools` docs (Apache-2.0).
- Crystal figure conventions in the README were surveyed via
  [scite.ai](https://scite.ai) Smart Citations; the cited papers belong to
  their respective publishers.

If you spot a missing attribution, please open an issue — the intent is
to credit everything this repo builds on.
