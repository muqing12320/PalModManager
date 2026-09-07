using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;
using System.Linq;
using System.Threading.Tasks;
using PalModManager.Core.Models;
using PalModManager.WinUI.Controls;
using PalModManager.WinUI.Services;
using Windows.Storage.Pickers;

namespace PalModManager.WinUI.Views;

public sealed partial class SettingsPage : Page
{
    private readonly BackendClient _client;

    public SettingsPage()
    {
        this.InitializeComponent();
        _client = App.ApiClient;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        _client.ModeChanged += OnModeChanged;
        UpdateModeLabels();

        if (!await _client.WaitUntilReadyAsync(TimeSpan.FromSeconds(10)))
        {
            ShowError("后端服务未就绪，请检查 Python 环境。");
            return;
        }

        await LoadConfigAsync();
        await LoadFrameworkStatusAsync();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        _client.ModeChanged -= OnModeChanged;
    }

    private async void OnModeChanged()
    {
        UpdateModeLabels();
        await LoadFrameworkStatusAsync();
    }

    private void UpdateModeLabels()
    {
        FrameworkHeader.Text = $"框架状态（{_client.ModeLabel}）";
    }

    private void ShowError(string message)
    {
        PageInfoBar.Severity = InfoBarSeverity.Error;
        PageInfoBar.Message = message;
        PageInfoBar.IsOpen = true;
    }

    private void ShowSuccess(string message)
    {
        PageInfoBar.Severity = InfoBarSeverity.Success;
        PageInfoBar.Message = message;
        PageInfoBar.IsOpen = true;
    }

    private bool _loadingConfig;

    private async Task LoadConfigAsync()
    {
        try
        {
            var config = await _client.GetConfigAsync<AppConfigDto>();
            if (config != null)
            {
                App.Config = config;
                GamePathTextBox.Text = config.GamePath ?? string.Empty;
                ServerPathTextBox.Text = config.ServerPath ?? string.Empty;
                // Assigning IsOn raises Toggled, whose handler saves the theme; without
                // this guard merely opening the page rewrites the stored theme.
                _loadingConfig = true;
                ThemeToggle.IsOn = config.Theme == "dark";
                _loadingConfig = false;
            }
        }
        catch (Exception ex)
        {
            ShowError($"读取配置失败：{ex.Message}");
        }
    }

    private async Task LoadFrameworkStatusAsync()
    {
        try
        {
            var status = await _client.GetFrameworksStatusAsync();
            if (status is null)
            {
                FrameworkStatusText.Text = "框架状态获取失败";
                return;
            }

            FrameworkStatusText.Text =
                $"UE4SS: {Describe(status.Ue4ssInstalled, status.Ue4ssVersion)} | " +
                $"PalSchema: {Describe(status.PalSchemaInstalled, status.PalSchemaVersion)}";
        }
        catch (Exception ex)
        {
            FrameworkStatusText.Text = $"框架状态获取失败：{ex.Message}";
        }
    }

    private static string Describe(bool installed, string? version)
    {
        if (!installed)
        {
            return "未安装";
        }

        return string.IsNullOrEmpty(version) ? "已安装" : $"已安装 {version}";
    }

    private async void BrowseGamePathButton_Click(object sender, RoutedEventArgs e)
    {
        var path = await PickFolderAsync();
        if (!string.IsNullOrEmpty(path))
        {
            GamePathTextBox.Text = path;
            await SaveConfigAsync();
        }
    }

    private async void DetectGamePathButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await _client.DetectGamePathAsync();
            if (string.IsNullOrEmpty(result?.Path))
            {
                ShowError("未找到帕鲁游戏安装路径。");
                return;
            }

            GamePathTextBox.Text = result!.Path;
            await SaveConfigAsync();
        }
        catch (Exception ex)
        {
            ShowError($"自动检测失败：{ex.Message}");
        }
    }

    private async void BrowseServerPathButton_Click(object sender, RoutedEventArgs e)
    {
        var path = await PickFolderAsync();
        if (!string.IsNullOrEmpty(path))
        {
            ServerPathTextBox.Text = path;
            await SaveConfigAsync();
        }
    }

    private async void DetectServerPathButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await _client.DetectServerPathAsync();
            if (string.IsNullOrEmpty(result?.Path))
            {
                ShowError("未找到 PalServer 安装路径。");
                return;
            }

            ServerPathTextBox.Text = result!.Path;
            await SaveConfigAsync();
        }
        catch (Exception ex)
        {
            ShowError($"自动检测失败：{ex.Message}");
        }
    }

    private async void InstallFrameworksButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await BusyDialog.RunAsync<FrameworkSetupResultDto?>(
                this.XamlRoot,
                "正在安装 UE4SS + PalSchema...",
                () => _client.InstallFrameworksAsync());

            if (result?.Success == true)
            {
                ShowSuccess("框架安装完成。");
            }
            else
            {
                ShowError(result is { Messages.Count: > 0 }
                    ? string.Join("\n", result.Messages)
                    : "框架安装未全部成功。");
            }

            await LoadFrameworkStatusAsync();
        }
        catch (Exception ex)
        {
            ShowError($"框架安装失败：{ex.Message}");
        }
    }

    private async void ThemeToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (_loadingConfig)
        {
            return;
        }

        var theme = ThemeToggle.IsOn ? "dark" : "light";
        App.ApplyTheme(theme);
        try
        {
            await _client.SetConfigAsync(new AppConfigDto { Theme = theme });
        }
        catch (Exception ex)
        {
            ShowError($"保存主题设置失败：{ex.Message}");
        }
    }

    private async void SyncToServerButton_Click(object sender, RoutedEventArgs e)
    {
        await RunSyncAsync("正在同步到服务器...", () => _client.SyncClientToServerAsync());
    }

    private async void SyncToClientButton_Click(object sender, RoutedEventArgs e)
    {
        await RunSyncAsync("正在同步到客户端...", () => _client.SyncServerToClientAsync());
    }

    private async Task RunSyncAsync(string busyMessage, Func<Task<SyncResultDto?>> action)
    {
        try
        {
            var result = await BusyDialog.RunAsync<SyncResultDto?>(this.XamlRoot, busyMessage, action);
            if (result is null)
            {
                ShowError("同步失败。");
                return;
            }

            ShowSuccess(result.Failed == 0
                ? $"已同步 {result.Copied} 个 Mod。"
                : $"已同步 {result.Copied} 个，失败 {result.Failed} 个：" +
                  string.Join("；", result.Errors.Take(3)));
        }
        catch (Exception ex)
        {
            ShowError($"同步失败：{ex.Message}");
        }
    }

    private async Task SaveConfigAsync()
    {
        try
        {
            var config = new AppConfigDto
            {
                GamePath = GamePathTextBox.Text,
                ServerPath = ServerPathTextBox.Text,
            };
            var saved = await _client.SetConfigAsync(config);
            if (saved != null)
            {
                App.Config = saved;
            }

            ShowSuccess("路径已保存。");
        }
        catch (Exception ex)
        {
            ShowError($"保存路径失败：{ex.Message}");
        }
    }

    private async Task<string?> PickFolderAsync()
    {
        var window = App.MainWindowInstance;
        if (window is null)
        {
            return null;
        }

        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
        };

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        return folder?.Path;
    }
}
