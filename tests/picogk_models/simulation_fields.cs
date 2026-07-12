using System.Numerics;
using Leap71.Simulation;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class SimulationFieldsModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        Library library = Library.oLibrary();
        Voxels domain = Voxels.voxSphere(library, Vector3.Zero, 8f);
        VectorField velocity = new VectorField(domain, new Vector3(0f, 0f, 1.5f));
        ScalarField density = ScalarUtil.oGetConstScalarField(velocity, 1000f);

        string output = context.OutputPath("simulation_fields.vdb");
        OpenVdbFile file = new OpenVdbFile(library);
        file.nAdd(domain, "Simulation.Domain_Fluid");
        file.nAdd(velocity, "Simulation.Field_Velocity");
        file.nAdd(density, "Simulation.Field_Density");
        file.SaveToFile(output);
        context.RegisterArtifact(
            output,
            "field_container",
            new
            {
                units = "mm",
                module = "simulation_example",
                fields = new[] { "Fluid", "Velocity", "Density" },
            }
        );
    }
}
