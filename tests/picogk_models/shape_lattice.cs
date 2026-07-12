using System.Numerics;
using Leap71.ShapeKernel;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class ShapeLatticeModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        BaseSphere boundary = new BaseSphere(new LocalFrame(), 14f);
        Voxels body = boundary.voxConstruct();

        Lattice lattice = new Lattice(Library.oLibrary());
        lattice.AddBeam(
            new Vector3(-12f, -12f, -12f),
            1.2f,
            new Vector3(12f, 12f, 12f),
            1.2f
        );
        lattice.AddBeam(
            new Vector3(-12f, 12f, -12f),
            1.2f,
            new Vector3(12f, -12f, 12f),
            1.2f
        );
        Voxels latticeVoxels = new Voxels(lattice);
        latticeVoxels.BoolIntersect(body);

        string output = context.OutputPath("shape_lattice.stl");
        latticeVoxels.mshAsMesh().SaveToStlFile(output);
        context.RegisterArtifact(
            output,
            "triangle_mesh",
            new { units = "mm", modules = new[] { "shape_kernel", "lattice_library" } }
        );
    }
}
