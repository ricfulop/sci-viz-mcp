using System.Numerics;
using System.Text.Json;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Tests;

public static class CoreRoundTrip
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        Library library = Library.oLibrary();
        Voxels body = Voxels.voxSphere(library, new Vector3(-3f, 0f, 0f), 10f);
        Voxels second = Voxels.voxSphere(library, new Vector3(6f, 0f, 0f), 7f);
        body.BoolAdd(second);

        Voxels cutter = Voxels.voxSphere(library, new Vector3(0f, 0f, 0f), 3f);
        body.BoolSubtract(cutter);
        body.Offset(0.25f);

        Lattice lattice = new Lattice(library);
        lattice.AddBeam(
            new Vector3(-12f, 0f, 0f),
            1.25f,
            new Vector3(15f, 0f, 0f),
            1.25f
        );
        Voxels beam = new Voxels(lattice);
        body.BoolAdd(beam);

        Voxels shell = body.voxShell(-1.5f, 0f);
        string stlPath = context.OutputPath("core_roundtrip.stl");
        shell.mshAsMesh().SaveToStlFile(stlPath);
        context.RegisterArtifact(stlPath, "triangle_mesh", new { units = "mm" });

        ScalarField scalar = new ScalarField(body, 42f);
        VectorField vector = new VectorField(body, new Vector3(1f, 2f, 3f));
        string vdbPath = context.OutputPath("core_fields.vdb");
        OpenVdbFile output = new OpenVdbFile(library);
        output.nAdd(body, "solid");
        output.nAdd(scalar, "temperature");
        output.nAdd(vector, "velocity");
        output.SaveToFile(vdbPath);

        OpenVdbFile loaded = new OpenVdbFile(library, vdbPath);
        if (loaded.nFieldCount() != 3)
            throw new Exception($"Expected 3 VDB fields, found {loaded.nFieldCount()}.");
        if (!loaded.bIsPicoGKCompatible())
            throw new Exception("Round-tripped VDB lacks PicoGK metadata.");
        Voxels loadedBody = loaded.voxGet("solid");
        ScalarField loadedScalar = loaded.oGetScalarField("temperature");
        VectorField loadedVector = loaded.oGetVectorField("velocity");
        if (loadedBody.bIsEmpty())
            throw new Exception("Round-tripped voxel body is empty.");
        if (!loadedScalar.bGetValue(new Vector3(-6f, 0f, 0f), out float scalarValue))
            throw new Exception("Round-tripped scalar field has no interior value.");
        if (!loadedVector.bGetValue(new Vector3(-6f, 0f, 0f), out Vector3 vectorValue))
            throw new Exception("Round-tripped vector field has no interior value.");

        context.RegisterArtifact(
            vdbPath,
            "field_container",
            new { units = "mm", fields = new[] { "solid", "temperature", "velocity" } }
        );
        string validationPath = context.OutputPath("validation.json");
        File.WriteAllText(
            validationPath,
            JsonSerializer.Serialize(
                new
                {
                    fields = loaded.nFieldCount(),
                    voxel_size_mm = loaded.fPicoGKVoxelSizeMM(),
                    scalar = scalarValue,
                    vector = new[] { vectorValue.X, vectorValue.Y, vectorValue.Z },
                },
                new JsonSerializerOptions { WriteIndented = true }
            )
        );
        context.RegisterArtifact(validationPath, "validation");
    }
}
