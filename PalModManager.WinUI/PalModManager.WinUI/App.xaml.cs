using Microsoft.UI.Xaml;
using PalModManager.Core.Models;
using PalModManager.WinUI.Services;
using System;
using System.Threading.Tasks;

namespace PalModManager.WinUI;

public partial class App : Application
{
    public static Window? MainWindowInstance { get; private set; }

    public static BackendProcessService? BackendService { get; private set; }

    /// <summary>
    /// Shared backend HTTP client used by all pages. Created eagerly so views can
    /// reference it during construction; it targets the backend's default port.
    /// </summary>
    public static BackendClient ApiClient { get; } = new BackendClient();

    /// <summary>
    /// Last config read from (or returned by) the backend. Used to gate the
    /// client/server mode switch on the matching install path being configured.
    /// </summary>
    public static AppConfigDto? Config { get; set; }

    public App()
    {
        this.InitializeComponent();
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        MainWindowInstance = new MainWindow();
        MainWindowInstance.Closed += (s, e) => BackendService?.Stop();
        MainWindowInstance.Activate();

        await StartBackendAsync();
    }

    private async Task StartBackendAsync()
    {
        try
        {
            BackendService = new BackendProcessService();
            var started = await BackendService.StartAsync();
            if (!started)
            {
                System.Diagnostics.Debug.WriteLine("Failed to start backend service.");
                return;
            }

            if (!await ApiClient.WaitUntilReadyAsync(TimeSpan.FromSeconds(15)))
            {
                return;
            }

            AppConfigDto? config = null;
            try
            {
                config = await ApiClient.GetConfigAsync<AppConfigDto>();
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Load config failed: {ex}");
            }

            if (config != null)
            {
                Config = config;
                ApplyTheme(config.Theme);
            }

            if (config?.AutoCheckUpdates == true && MainWindowInstance is MainWindow window)
            {
                _ = window.CheckForUpdateAsync(silent: true);
            }
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"Backend start error: {ex}");
        }
    }

    public static void ApplyTheme(string? theme)
    {
        if (MainWindowInstance?.Content is not FrameworkElement root)
        {
            return;
        }

        root.RequestedTheme = theme switch
        {
            "dark" => ElementTheme.Dark,
            "light" => ElementTheme.Light,
            _ => ElementTheme.Default,
        };
    }
}
