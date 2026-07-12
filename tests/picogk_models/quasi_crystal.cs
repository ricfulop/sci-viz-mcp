using Leap71.AperiodicTiling;
using Leap71.ShapeKernel;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class QuasiCrystalModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        QuasiTile seed = new QuasiTile_01(new LocalFrame(), 8f);
        QuasiCrystal crystal = new QuasiCrystal(
            1,
            new List<QuasiTile> { seed }
        );
        Voxels wireframe = crystal.voxGetWireframe(0, 0.8f);
        string output = context.OutputPath("quasi_crystal.stl");
        wireframe.mshAsMesh().SaveToStlFile(output);
        context.RegisterArtifact(
            output,
            "triangle_mesh",
            new { units = "mm", module = "quasi_crystals" }
        );
    }
}
