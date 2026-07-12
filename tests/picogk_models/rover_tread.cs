using Leap71.Rover;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class RoverTreadModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        TreadPattern_01 pattern = new TreadPattern_01();
        Voxels tread = pattern.voxConstruct(
            15f,
            8f,
            point => point
        );
        string output = context.OutputPath("rover_tread.stl");
        tread.mshAsMesh().SaveToStlFile(output);
        context.RegisterArtifact(
            output,
            "triangle_mesh",
            new { units = "mm", module = "rover_wheel" }
        );
    }
}
