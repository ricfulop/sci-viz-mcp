using System.Numerics;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Example;

public static class ExampleModel
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
        string outputPath = context.OutputPath("sphere.stl");
        mesh.SaveToStlFile(outputPath);
        context.RegisterArtifact(
            outputPath,
            "triangle_mesh",
            new { units = "mm", primitive = "sphere", radius_mm = 10f }
        );
    }
}
