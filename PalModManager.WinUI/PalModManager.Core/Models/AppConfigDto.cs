using System.Text.Json.Serialization;

namespace PalModManager.Core.Models;

public class AppConfigDto
{
    [JsonPropertyName("game_path")]
    public string? GamePath { get; set; }

    [JsonPropertyName("server_path")]
    public string? ServerPath { get; set; }

    [JsonPropertyName("theme")]
    public string? Theme { get; set; }

    [JsonPropertyName("language")]
    public string? Language { get; set; }

    [JsonPropertyName("auto_check_updates")]
    public bool? AutoCheckUpdates { get; set; }
}
