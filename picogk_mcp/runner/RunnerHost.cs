using System.Reflection;
using System.Text.Json;
using PicoGK;

namespace SciViz.PicoGK.Runner;

[AttributeUsage(AttributeTargets.Method, AllowMultiple = false)]
public sealed class PicoGKTaskAttribute : Attribute
{
}

public sealed class JobContext
{
    private readonly string _outputPrefix;
    private readonly string _artifactLog;
    private readonly object _artifactLock = new();

    public JobContext(string jobId, string outputDirectory, float voxelSizeMm)
    {
        JobId = jobId;
        OutputDirectory = Path.GetFullPath(outputDirectory);
        Directory.CreateDirectory(OutputDirectory);
        _outputPrefix = OutputDirectory.EndsWith(Path.DirectorySeparatorChar)
            ? OutputDirectory
            : OutputDirectory + Path.DirectorySeparatorChar;
        _artifactLog = Path.Combine(OutputDirectory, "artifacts.jsonl");
        VoxelSizeMm = voxelSizeMm;
    }

    public string JobId { get; }
    public string OutputDirectory { get; }
    public float VoxelSizeMm { get; }

    public string OutputPath(string relativePath)
    {
        if (string.IsNullOrWhiteSpace(relativePath) || Path.IsPathRooted(relativePath))
            throw new ArgumentException("Artifact path must be relative.", nameof(relativePath));

        string fullPath = Path.GetFullPath(Path.Combine(OutputDirectory, relativePath));
        if (!fullPath.StartsWith(_outputPrefix, StringComparison.Ordinal))
            throw new ArgumentException("Artifact path escapes the job output directory.", nameof(relativePath));

        string? parent = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(parent))
            Directory.CreateDirectory(parent);
        return fullPath;
    }

    public void RegisterArtifact(string path, string kind = "file", object? metadata = null)
    {
        string fullPath = Path.GetFullPath(path);
        if (!fullPath.StartsWith(_outputPrefix, StringComparison.Ordinal))
            throw new ArgumentException("Only files under JobContext.OutputDirectory can be registered.", nameof(path));

        var record = new
        {
            path = fullPath,
            kind,
            metadata,
            registered_at = DateTimeOffset.UtcNow,
        };
        lock (_artifactLock)
        {
            File.AppendAllText(_artifactLog, JsonSerializer.Serialize(record) + Environment.NewLine);
        }
    }
}

internal sealed record RunnerResult(
    string Status,
    string JobId,
    string ViewerMode,
    float VoxelSizeMm,
    DateTimeOffset StartedAt,
    DateTimeOffset EndedAt,
    string? ErrorType = null,
    string? Error = null,
    string? StackTrace = null
);

public static class Program
{
    public static int Main()
    {
        string jobId = RequiredEnvironment("PICOGK_JOB_ID");
        string outputDirectory = RequiredEnvironment("PICOGK_JOB_OUTPUT_DIR");
        string resultPath = RequiredEnvironment("PICOGK_RUNNER_RESULT");
        string logPath = RequiredEnvironment("PICOGK_LOG_FILE");
        string viewerMode = Environment.GetEnvironmentVariable("PICOGK_VIEWER_MODE") ?? "viewer_autoclose";
        float voxelSizeMm = ParseVoxelSize();
        var startedAt = DateTimeOffset.UtcNow;

        try
        {
            var context = new JobContext(jobId, outputDirectory, voxelSizeMm);
            Action task = () => InvokeTask(context);

            switch (viewerMode)
            {
                case "headless":
                    RunHeadless(voxelSizeMm, logPath, task);
                    break;
                case "viewer_autoclose":
                    RunViewer(voxelSizeMm, logPath, task, closeWithTask: true);
                    break;
                case "viewer_interactive":
                    RunViewer(voxelSizeMm, logPath, task, closeWithTask: false);
                    break;
                default:
                    throw new ArgumentException(
                        $"Unknown PICOGK_VIEWER_MODE '{viewerMode}'. " +
                        "Use headless, viewer_autoclose, or viewer_interactive."
                    );
            }

            WriteResult(
                resultPath,
                new RunnerResult(
                    "succeeded",
                    jobId,
                    viewerMode,
                    voxelSizeMm,
                    startedAt,
                    DateTimeOffset.UtcNow
                )
            );
            return 0;
        }
        catch (Exception exception)
        {
            Exception error = Unwrap(exception);
            WriteResult(
                resultPath,
                new RunnerResult(
                    "failed",
                    jobId,
                    viewerMode,
                    voxelSizeMm,
                    startedAt,
                    DateTimeOffset.UtcNow,
                    error.GetType().FullName,
                    error.Message,
                    error.StackTrace
                )
            );
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static void RunHeadless(float voxelSizeMm, string logPath, Action task)
    {
        using var log = new LogFile(logPath);
        using var library = new Library(voxelSizeMm);
        Library.RegisterGlobalLibrary(library);
        Library.RegisterGlobalLog(log);
        try
        {
            task();
        }
        finally
        {
            Library.UnregisterGlobalLog();
            Library.UnregisterGlobalLibrary();
        }
    }

    private static void RunViewer(
        float voxelSizeMm,
        string logPath,
        Action task,
        bool closeWithTask
    )
    {
        Exception? taskError = null;
        void GuardedTask()
        {
            try
            {
                task();
            }
            catch (Exception exception)
            {
                taskError = Unwrap(exception);
            }
        }

        Library.Go(
            voxelSizeMm,
            GuardedTask,
            strLogFilePath: logPath,
            bEndAppWithTask: closeWithTask,
            strWindowTitle: "Sci-Viz PicoGK"
        );
        if (taskError is not null)
            throw taskError;
    }

    private static void InvokeTask(JobContext context)
    {
        MethodInfo[] methods = Assembly.GetExecutingAssembly()
            .GetTypes()
            .SelectMany(type => type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
            .Where(method => method.GetCustomAttribute<PicoGKTaskAttribute>() is not null)
            .ToArray();

        if (methods.Length != 1)
            throw new InvalidOperationException(
                $"Expected exactly one static method marked [PicoGKTask], found {methods.Length}."
            );

        MethodInfo method = methods[0];
        ParameterInfo[] parameters = method.GetParameters();
        object?[] arguments = parameters.Length switch
        {
            0 => [],
            1 when parameters[0].ParameterType == typeof(JobContext) => [context],
            _ => throw new InvalidOperationException(
                "[PicoGKTask] must accept no parameters or one JobContext parameter."
            ),
        };
        method.Invoke(null, arguments);
    }

    private static float ParseVoxelSize()
    {
        string raw = Environment.GetEnvironmentVariable("PICOGK_VOXEL_SIZE_MM") ?? "0.5";
        if (!float.TryParse(raw, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out float value) ||
            !float.IsFinite(value) ||
            value <= 0)
        {
            throw new ArgumentException($"Invalid PICOGK_VOXEL_SIZE_MM '{raw}'.");
        }
        return value;
    }

    private static string RequiredEnvironment(string name)
    {
        string? value = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidOperationException($"Required environment variable {name} is not set.");
        return value;
    }

    private static Exception Unwrap(Exception exception)
    {
        while (exception is TargetInvocationException && exception.InnerException is not null)
            exception = exception.InnerException;
        return exception;
    }

    private static void WriteResult(string path, RunnerResult result)
    {
        string fullPath = Path.GetFullPath(path);
        string? parent = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(parent))
            Directory.CreateDirectory(parent);
        string temporary = fullPath + ".tmp";
        File.WriteAllText(
            temporary,
            JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true })
        );
        File.Move(temporary, fullPath, overwrite: true);
    }
}
