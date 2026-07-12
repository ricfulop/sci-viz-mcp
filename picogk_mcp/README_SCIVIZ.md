# PicoGK MCP

`picogk_mcp` gives MCP clients full C# access to
[PicoGK 2.2](https://github.com/leap71/PicoGK) and the public LEAP 71
computational-engineering stack. It compiles each model into a deterministic
.NET 9 job and runs it in a separate process.

## Compatibility

- .NET SDK 9
- macOS ARM64 or Windows x64 for native execution
- Linux can list tools and compile jobs, but PicoGK 2.2 does not ship a Linux
  native runtime
- PicoGK geometry is voxel/SDF based and uses millimetres; it is not exact
  B-rep CAD and does not export STEP

Install the local SDK, build the runner, and optionally fetch every locked
LEAP 71 source module:

```bash
./install.sh --with-picogk --sync-picogk
```

The simulation example repository does not declare a software license. It is
not fetched by default:

```bash
./install.sh --with-picogk --sync-picogk \
  --include-unlicensed-picogk
```

All source-only modules are checked out at exact commits from
`stack.lock.json` under `~/.cache/sci-viz-mcp/picogk/`. Sci-Viz never follows
upstream `main` during a build.

## Security model

`picogk_run_csharp` is intentionally a trusted-local execution tool. Submitted
C# has the same filesystem and network permissions as the MCP server. A job
runs in a child process with cancellation, timeout, and separate logs, but
that is not an operating-system sandbox. Do not execute untrusted source.

## C# task contract

Provide exactly one static method marked `[PicoGKTask]`. It can accept no
arguments or one `JobContext`:

```csharp
using System.Numerics;
using PicoGK;
using SciViz.PicoGK.Runner;

public static class Model
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        Voxels sphere = Voxels.voxSphere(
            Library.oLibrary(),
            Vector3.Zero,
            10f
        );
        Mesh mesh = sphere.mshAsMesh();
        string path = context.OutputPath("sphere.stl");
        mesh.SaveToStlFile(path);
        context.RegisterArtifact(
            path,
            "triangle_mesh",
            new { units = "mm" }
        );
    }
}
```

`OutputPath()` rejects absolute and escaping paths. `RegisterArtifact()`
attaches kind and metadata to the job manifest. Because the C# is trusted,
source can still use ordinary .NET APIs directly.

## Source modules

- `shape_kernel`: primitives, sweeps, frames, splines, implicits, offsets,
  and visualization helpers
- `lattice_library`: regular/conformal beam lattices, thickness fields, and
  TPMS implicit structures
- `quasi_crystals`: Penrose tilings and icosahedral quasi-crystals
- `rover_wheel`: layered rover wheels, treads, and conformal strut systems
- `helix_heatx`: helical two-stream heat-exchanger CEM
- `picogk_examples`: official getting-started examples
- `simulation_example`: scalar/vector fields and VDB simulation interchange;
  explicit license opt-in required

Dependencies are selected automatically. Modules must be named explicitly on
the project or one-shot run so unrelated example code is not compiled into
every model.

## Tools

| Group | Tools |
|---|---|
| Environment | `picogk_health`, `picogk_stack_info`, `picogk_sync_stack`, `picogk_reference` |
| Projects | `picogk_create_project`, `picogk_list_projects`, `picogk_get_project`, `picogk_write_source` |
| Build/run | `picogk_build`, `picogk_run`, `picogk_run_csharp` |
| Jobs | `picogk_job_status`, `picogk_list_jobs`, `picogk_cancel_job`, `picogk_job_logs` |
| Artifacts | `picogk_list_artifacts`, `picogk_preview_artifact` |

Builds are cached by source, runner, module list, and stack-lock hash. A source
or dependency revision change creates a new build.

## Viewer modes

- `headless`: geometry and field operations only. Code that calls
  `Library.oViewer()` fails because no viewer is registered.
- `viewer_autoclose`: uses upstream `Library.Go`; closes after the task and
  queued viewer actions finish.
- `viewer_interactive`: leaves the viewer open. Run asynchronously and close
  the viewer or call `picogk_cancel_job`.

## Artifacts and provenance

Jobs live under `output/picogk/jobs/<job_id>/`. `job.json` records:

- source and stack-lock hashes
- exact PicoGK version and LEAP 71 module commits
- voxel size, runtime identifier, viewer mode, and timing
- status, exit code, and bounded logs
- each artifact's SHA-256, byte size, kind, units, and metadata

PNG, JPEG, SVG, and PDF artifacts are sent to the live preview dashboard.
STL, OBJ, and VDB are returned as paths for Blender, OVITO, slicers, or other
downstream tools.

## Troubleshooting

- `dotnet was not found`: rerun `./install.sh --with-picogk` or set
  `PICOGK_MCP_DOTNET`.
- unsupported native RID: PicoGK 2.2's NuGet package contains `osx-arm64` and
  `win-x64` native libraries only.
- module is not synchronized: call `picogk_sync_stack` for that module.
- code works with a viewer but not headless: it likely calls
  `Library.oViewer()`; select `viewer_autoclose`.
- compile errors in old examples: inspect `picogk_job_logs`; the Sci-Viz
  project targets .NET 9 while preserving cached upstream source unchanged.

