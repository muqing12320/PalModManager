namespace PalModManager.Core.Models;

public enum ModType
{
    UE4SS_LUA,
    UE4SS_BLUEPRINT,
    PAK,
    PALSCHEMA,
    LOGIC,
    UNKNOWN
}

public enum ModStatus
{
    ENABLED,
    DISABLED,
    CONFLICT,
    ERROR,
    UNKNOWN
}

public class ModInfo
{
    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Version { get; set; } = "1.0.0";
    public string Author { get; set; } = "Unknown";
    public string Description { get; set; } = string.Empty;
    public ModType ModType { get; set; } = ModType.UNKNOWN;
    public ModStatus Status { get; set; } = ModStatus.UNKNOWN;
    public string InstallPath { get; set; } = string.Empty;
    public string SourcePath { get; set; } = string.Empty;
    public List<string> Dependencies { get; set; } = new();
    public List<string> RequiredFrameworks { get; set; } = new();
    public List<string> Tags { get; set; } = new();
    public string InstalledDate { get; set; } = string.Empty;
    public string LastUpdated { get; set; } = string.Empty;
    public bool IsAutoManaged { get; set; } = true;
}
