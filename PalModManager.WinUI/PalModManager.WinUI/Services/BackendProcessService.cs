using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace PalModManager.WinUI.Services;

public class BackendProcessService
{
    private Process? _process;

    public int Port { get; private set; }

    public async Task<bool> StartAsync()
    {
        var backendPath = FindBackendScript();
        if (string.IsNullOrEmpty(backendPath))
        {
            return false;
        }

        // api_server.py lives at <root>/src/backend/, and `-m src.backend.api_server`
        // only resolves when the child process starts in <root>.
        var backendDir = new DirectoryInfo(Path.GetDirectoryName(backendPath)!);
        var projectRoot = backendDir.Parent?.Parent?.FullName;
        if (string.IsNullOrEmpty(projectRoot) || !Directory.Exists(Path.Combine(projectRoot, "src")))
        {
            return false;
        }

        var pythonExe = FindPythonExecutable();
        if (string.IsNullOrEmpty(pythonExe))
        {
            return false;
        }

        var psi = new ProcessStartInfo
        {
            FileName = pythonExe,
            Arguments = "-m src.backend.api_server --port 5000",
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };

        _process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        _process.Start();

        var tcs = new TaskCompletionSource<bool>();
        _process.OutputDataReceived += (sender, e) =>
        {
            if (!string.IsNullOrEmpty(e.Data) && e.Data.StartsWith("PALMOD_BACKEND_PORT="))
            {
                if (int.TryParse(e.Data["PALMOD_BACKEND_PORT=".Length..], out var port))
                {
                    Port = port;
                    tcs.TrySetResult(true);
                }
            }
        };

        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();

        var completedTask = await Task.WhenAny(tcs.Task, Task.Delay(TimeSpan.FromSeconds(10)));
        return completedTask == tcs.Task;
    }

    public void Stop()
    {
        try
        {
            _process?.Kill(true);
        }
        catch
        {
            // ignore
        }
    }

    private static string? FindBackendScript()
    {
        // Walk up from the output directory: in a checkout that reaches the repo root,
        // and a published app finds src next to the exe on the first iteration.
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var depth = 0; dir is not null && depth < 8; depth++)
        {
            var candidate = Path.Combine(dir.FullName, "src", "backend", "api_server.py");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            dir = dir.Parent;
        }

        return null;
    }

    private static string? FindPythonExecutable()
    {
        // Prefer a packaged python next to the app
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "python", "python.exe"),
            Path.Combine(AppContext.BaseDirectory, "python.exe"),
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        // Fall back to PATH python (prefer python.exe so stdin remains available
        // for the parent-EOF watchdog; CreateNoWindow already hides the console).
        foreach (var name in new[] { "python.exe", "pythonw.exe" })
        {
            var path = FindInPath(name);
            if (!string.IsNullOrEmpty(path))
            {
                return path;
            }
        }

        return null;
    }

    private static string? FindInPath(string fileName)
    {
        var pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(pathEnv))
        {
            return null;
        }

        foreach (var dir in pathEnv.Split(Path.PathSeparator))
        {
            var full = Path.Combine(dir, fileName);
            if (File.Exists(full))
            {
                return full;
            }
        }

        return null;
    }
}
