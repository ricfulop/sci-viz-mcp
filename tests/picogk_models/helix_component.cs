using Leap71.ConstructionModules;
using Leap71.ShapeKernel;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class HelixComponentModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        ScrewHole screw = new ScrewHole(
            new LocalFrame(),
            12f,
            2f,
            3f,
            4f
        );
        Voxels geometry = screw.voxConstruct();
        string output = context.OutputPath("helix_component.stl");
        geometry.mshAsMesh().SaveToStlFile(output);
        context.RegisterArtifact(
            output,
            "triangle_mesh",
            new { units = "mm", module = "helix_heatx" }
        );
    }
}
