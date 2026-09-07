using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using PalModManager.Core.Models;

namespace PalModManager.WinUI.Services;

public class BackendClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public BackendClient(string baseUrl)
    {
        _baseUrl = baseUrl.TrimEnd('/');
        // Framework install and mod export move large trees; a short timeout would
        // abort them client-side while the backend keeps working. A dead backend still
        // fails fast because the connection to 127.0.0.1 is refused.
        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(15) };
    }

    public BackendClient() : this(DefaultBaseUrl)
    {
    }

    public const string DefaultBaseUrl = "http://127.0.0.1:5000";

    public const string GameMode = "game";

    public const string ServerMode = "server";

    public string BaseUrl => _baseUrl;

    private string _mode = GameMode;

    /// <summary>
    /// Which install the UI is managing. Optional mode arguments on the calls below
    /// fall back to this, so switching it re-points every feature at the other install.
    /// </summary>
    public string Mode
    {
        get => _mode;
        set
        {
            var next = value == ServerMode ? ServerMode : GameMode;
            if (_mode == next)
            {
                return;
            }

            _mode = next;
            ModeChanged?.Invoke();
        }
    }

    public bool IsServerMode => _mode == ServerMode;

    public string ModeLabel => IsServerMode ? "服务器" : "客户端";

    public event Action? ModeChanged;

    public async Task<bool> HealthAsync()
    {
        try
        {
            var response = await _http.GetAsync($"{_baseUrl}/api/health");
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<bool> WaitUntilReadyAsync(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await HealthAsync())
            {
                return true;
            }

            await Task.Delay(300);
        }

        return false;
    }

    public async Task<StatsDto?> GetStatsAsync(string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.GetAsync($"{_baseUrl}/api/stats?mode={mode}");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<StatsDto>(json, JsonOptions);
    }

    public async Task<List<ModInfo>> GetModsAsync(string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.GetAsync($"{_baseUrl}/api/mods?mode={mode}");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var result = new List<ModInfo>();
        if (doc.RootElement.TryGetProperty("mods", out var mods))
        {
            foreach (var item in mods.EnumerateArray())
            {
                result.Add(ParseModInfo(item));
            }
        }
        return result;
    }

    public async Task<ModInfo?> ToggleModAsync(string modId, string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.PostAsync($"{_baseUrl}/api/mods/{Uri.EscapeDataString(modId)}/toggle?mode={mode}", null);
        await EnsureFlagTrueAsync(response, $"Mod {modId} 状态切换失败");
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.TryGetProperty("mod", out var modElement) && modElement.ValueKind != JsonValueKind.Null)
        {
            return ParseModInfo(modElement);
        }
        return null;
    }

    public async Task EnableAllAsync(string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.PostAsync($"{_baseUrl}/api/mods/enable_all?mode={mode}", null);
        await EnsureSuccessAsync(response);
    }

    public async Task DisableAllAsync(string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.PostAsync($"{_baseUrl}/api/mods/disable_all?mode={mode}", null);
        await EnsureSuccessAsync(response);
    }

    public async Task<string> DeleteModAsync(string modId, string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.DeleteAsync($"{_baseUrl}/api/mods/{Uri.EscapeDataString(modId)}?mode={mode}");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.TryGetProperty("backup_error", out var err) ? err.GetString() ?? string.Empty : string.Empty;
    }

    public async Task<ModInfo?> ImportModAsync(string sourcePath, string? mode = null)
    {
        mode ??= Mode;
        var payload = new { source_path = sourcePath, mode };
        var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/mods/import", content);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.TryGetProperty("mod", out var modElement) && modElement.ValueKind != JsonValueKind.Null)
        {
            return ParseModInfo(modElement);
        }
        return null;
    }

    public async Task<ExportResultDto?> ExportModsAsync(string outputDir, string? mode = null)
    {
        mode ??= Mode;
        var payload = new { output_dir = outputDir, mode };
        var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/mods/export", content);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<ExportResultDto>(json, JsonOptions);
    }

    public async Task<List<ModInfo>> ScanCollectionAsync(string collectionDir, string? mode = null)
    {
        mode ??= Mode;
        var payload = new { collection_dir = collectionDir, mode };
        var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/collection/scan", content);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var result = new List<ModInfo>();
        if (doc.RootElement.TryGetProperty("mods", out var mods))
        {
            foreach (var item in mods.EnumerateArray())
            {
                result.Add(ParseModInfo(item));
            }
        }
        return result;
    }

    public async Task<T?> GetConfigAsync<T>()
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/config");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<T>(json, JsonOptions);
    }

    public async Task<T?> SetConfigAsync<T>(T config)
    {
        var content = new StringContent(JsonSerializer.Serialize(config), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/config", content);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<T>(json, JsonOptions);
    }

    public async Task<DetectPathDto?> DetectGamePathAsync()
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/game/detect");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<DetectPathDto>(json, JsonOptions);
    }

    public async Task<DetectPathDto?> DetectServerPathAsync()
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/server/detect");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<DetectPathDto>(json, JsonOptions);
    }

    public async Task<FrameworkStatusDto?> GetFrameworksStatusAsync(string? mode = null)
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/frameworks/status?{ModeQuery(mode)}");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<FrameworkStatusDto>(json, JsonOptions);
    }

    public async Task<FrameworkSetupResultDto?> InstallFrameworksAsync(string? mode = null)
    {
        var response = await _http.PostAsync($"{_baseUrl}/api/frameworks/setup?{ModeQuery(mode)}", null);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<FrameworkSetupResultDto>(json, JsonOptions);
    }

    public async Task<SyncResultDto?> SyncClientToServerAsync()
    {
        var response = await _http.PostAsync($"{_baseUrl}/api/sync/client_to_server", null);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<SyncResultDto>(json, JsonOptions);
    }

    public async Task<SyncResultDto?> SyncServerToClientAsync()
    {
        var response = await _http.PostAsync($"{_baseUrl}/api/sync/server_to_client", null);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<SyncResultDto>(json, JsonOptions);
    }

    public async Task<List<ProfileDto>> GetProfilesAsync(string? mode = null)
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/profiles?{ModeQuery(mode)}");
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<ProfileListDto>(json, JsonOptions)?.Profiles ?? new List<ProfileDto>();
    }

    public async Task CreateProfileAsync(string name, string description = "", string? mode = null)
    {
        var payload = new { name, description };
        var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/profiles?{ModeQuery(mode)}", content);
        await EnsureSuccessAsync(response);
    }

    public async Task LoadProfileAsync(string name, string? mode = null)
    {
        var response = await _http.PostAsync(
            $"{_baseUrl}/api/profiles/{Uri.EscapeDataString(name)}/load?{ModeQuery(mode)}", null);
        await EnsureFlagTrueAsync(response, $"方案 {name} 不存在或加载失败");
    }

    public async Task DeleteProfileAsync(string name, string? mode = null)
    {
        var response = await _http.DeleteAsync(
            $"{_baseUrl}/api/profiles/{Uri.EscapeDataString(name)}?{ModeQuery(mode)}");
        await EnsureFlagTrueAsync(response, $"方案 {name} 不存在");
    }

    public async Task<LaunchResultDto?> LaunchGameAsync(string? mode = null)
    {
        mode ??= Mode;
        var payload = new { mode };
        var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/game/launch", content);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<LaunchResultDto>(json, JsonOptions);
    }

    public async Task<UpdateCheckResult> CheckUpdateAsync()
    {
        try
        {
            var response = await _http.GetAsync($"{_baseUrl}/api/update/check");
            var json = await response.Content.ReadAsStringAsync();
            if (!response.IsSuccessStatusCode)
            {
                return new UpdateCheckResult { Ok = false, Error = ExtractError(json) };
            }

            var dto = JsonSerializer.Deserialize<UpdateCheckDto>(json, JsonOptions);
            return new UpdateCheckResult
            {
                Ok = true,
                CurrentVersion = dto?.CurrentVersion ?? string.Empty,
                Update = dto?.Update,
            };
        }
        catch (Exception ex)
        {
            return new UpdateCheckResult { Ok = false, Error = ex.Message };
        }
    }

    public async Task<string?> DownloadUpdateWithProgressAsync(IProgress<double>? progress = null)
    {
        using var streamingClient = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        var request = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}/api/update/download-stream");
        var response = await streamingClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
        await EnsureSuccessAsync(response);

        await using var stream = await response.Content.ReadAsStreamAsync();
        using var reader = new StreamReader(stream);

        while (true)
        {
            var line = await reader.ReadLineAsync();
            if (line is null)
            {
                break;
            }

            const string prefix = "data: ";
            if (!line.StartsWith(prefix, StringComparison.Ordinal))
            {
                continue;
            }

            var payload = line[prefix.Length..];
            using var doc = JsonDocument.Parse(payload);
            var root = doc.RootElement;
            switch (root.GetProperty("type").GetString())
            {
                case "progress":
                    var done = root.GetProperty("done").GetInt64();
                    var total = root.GetProperty("total").GetInt64();
                    if (total > 0)
                    {
                        progress?.Report((double)done / total);
                    }
                    break;
                case "done":
                    return root.GetProperty("path").GetString();
                case "error":
                    throw new InvalidOperationException(
                        root.GetProperty("message").GetString() ?? "下载失败");
            }
        }

        return null;
    }

    public async Task<RepairResultDto?> RepairAsync(string? mode = null)
    {
        mode ??= Mode;
        var response = await _http.PostAsync($"{_baseUrl}/api/repair?mode={mode}", null);
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<RepairResultDto>(json, JsonOptions);
    }

    private string ModeQuery(string? mode) => $"mode={mode ?? Mode}";

    private static async Task EnsureSuccessAsync(HttpResponseMessage response)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        var json = await response.Content.ReadAsStringAsync();
        throw new InvalidOperationException(ExtractError(json));
    }

    private static async Task EnsureFlagTrueAsync(HttpResponseMessage response, string failureMessage)
    {
        await EnsureSuccessAsync(response);
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False)
        {
            throw new InvalidOperationException(failureMessage);
        }
    }

    private static string ExtractError(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind == JsonValueKind.Object &&
                doc.RootElement.TryGetProperty("error", out var error) &&
                error.ValueKind == JsonValueKind.String)
            {
                return error.GetString() ?? "请求失败";
            }
        }
        catch (JsonException)
        {
            // Non-JSON body (proxy page, Flask HTML traceback).
        }

        return string.IsNullOrWhiteSpace(json) ? "请求失败" : json;
    }

    private static ModInfo ParseModInfo(JsonElement element)
    {
        var mod = new ModInfo
        {
            Id = GetString(element, "id"),
            Name = GetString(element, "name"),
            Version = GetString(element, "version"),
            Author = GetString(element, "author"),
            Description = GetString(element, "description"),
            InstallPath = GetString(element, "install_path"),
            SourcePath = GetString(element, "source_path"),
        };

        if (element.TryGetProperty("mod_type", out var typeProp))
        {
            mod.ModType = ParseModType(typeProp.GetString());
        }

        if (element.TryGetProperty("status", out var statusProp) &&
            Enum.TryParse<ModStatus>(statusProp.GetString(), true, out var status))
        {
            mod.Status = status;
        }

        return mod;
    }

    private static string GetString(JsonElement element, string propertyName)
    {
        if (element.TryGetProperty(propertyName, out var prop) && prop.ValueKind != JsonValueKind.Null)
        {
            return prop.GetString() ?? string.Empty;
        }
        return string.Empty;
    }

    private static ModType ParseModType(string? value)
    {
        return value?.ToLowerInvariant() switch
        {
            "ue4ss_lua" => ModType.UE4SS_LUA,
            "ue4ss_bp" => ModType.UE4SS_BLUEPRINT,
            "pak" => ModType.PAK,
            "palschema" => ModType.PALSCHEMA,
            "logic_mod" => ModType.LOGIC,
            _ => ModType.UNKNOWN,
        };
    }
}

public class StatsDto
{
    public int Total { get; set; }
    public int Enabled { get; set; }
    public int Disabled { get; set; }
    public int Conflict { get; set; }
}

public class ExportResultDto
{
    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("path")]
    public string? Path { get; set; }

    [JsonPropertyName("errors")]
    public List<string> Errors { get; set; } = new();
}

public class DetectPathDto
{
    [JsonPropertyName("path")]
    public string? Path { get; set; }

    [JsonPropertyName("valid")]
    public bool Valid { get; set; }
}

public class LaunchResultDto
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }
}

public class RepairResultDto
{
    [JsonPropertyName("fixed")]
    public int FixedCount { get; set; }

    [JsonPropertyName("messages")]
    public List<string> Messages { get; set; } = new();
}

public class FrameworkStatusDto
{
    [JsonPropertyName("ue4ss_installed")]
    public bool Ue4ssInstalled { get; set; }

    [JsonPropertyName("ue4ss_version")]
    public string? Ue4ssVersion { get; set; }

    [JsonPropertyName("palschema_installed")]
    public bool PalSchemaInstalled { get; set; }

    [JsonPropertyName("palschema_version")]
    public string? PalSchemaVersion { get; set; }

    [JsonPropertyName("all_ready")]
    public bool AllReady { get; set; }
}

public class FrameworkSetupResultDto
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("messages")]
    public List<string> Messages { get; set; } = new();
}

public class SyncResultDto
{
    [JsonPropertyName("copied")]
    public int Copied { get; set; }

    [JsonPropertyName("failed")]
    public int Failed { get; set; }

    [JsonPropertyName("errors")]
    public List<string> Errors { get; set; } = new();
}

public class ProfileListDto
{
    [JsonPropertyName("profiles")]
    public List<ProfileDto> Profiles { get; set; } = new();
}

public class ProfileDto
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;

    [JsonPropertyName("created_date")]
    public string CreatedDate { get; set; } = string.Empty;

    [JsonPropertyName("enabled_mods")]
    public List<string> EnabledMods { get; set; } = new();
}

public class UpdateCheckDto
{
    [JsonPropertyName("current_version")]
    public string CurrentVersion { get; set; } = string.Empty;

    [JsonPropertyName("update")]
    public UpdateInfoDto? Update { get; set; }
}

public class UpdateInfoDto
{
    [JsonPropertyName("version")]
    public string Version { get; set; } = string.Empty;

    [JsonPropertyName("download_url")]
    public string DownloadUrl { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public string Notes { get; set; } = string.Empty;
}

public class UpdateCheckResult
{
    public bool Ok { get; init; }

    public string Error { get; init; } = string.Empty;

    public string CurrentVersion { get; init; } = string.Empty;

    public UpdateInfoDto? Update { get; init; }

    public bool HasUpdate => !string.IsNullOrEmpty(Update?.Version);
}
