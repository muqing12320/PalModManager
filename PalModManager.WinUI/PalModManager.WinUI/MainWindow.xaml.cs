using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Windowing;
using PalModManager.WinUI.Controls;
using PalModManager.WinUI.Services;
using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace PalModManager.WinUI;

public sealed partial class MainWindow : Window
{
    private bool _updateFlowActive;

    // ContentDialogs need the XamlRoot owned by the window's root element,
    // because Microsoft.UI.Xaml.Window does not expose one itself.
    private XamlRoot DialogRoot => ((FrameworkElement)Content).XamlRoot;

    public MainWindow()
    {
        this.InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        Title = "帕鲁Mod管理器";
        ResizeWindow();
        NavView.SelectedItem = NavView.MenuItems[0];
        ContentFrame.Navigate(typeof(Views.ModsPage));
        UpdateModeUi();
    }

    private void ResizeWindow()
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        AppWindow.GetFromWindowId(windowId).Resize(new Windows.Graphics.SizeInt32(1500, 900));
    }

    private async void ModeButton_Click(object sender, RoutedEventArgs e)
    {
        var client = App.ApiClient;
        var toServer = !client.IsServerMode;
        var hasPath = toServer
            ? !string.IsNullOrWhiteSpace(App.Config?.ServerPath)
            : !string.IsNullOrWhiteSpace(App.Config?.GamePath);
        if (!hasPath)
        {
            await ShowMessageAsync(
                "切换模式",
                toServer
                    ? "请先在「设置与框架」中配置 PalServer 安装路径。"
                    : "请先在「设置与框架」中配置游戏客户端安装路径。");
            return;
        }

        client.Mode = toServer ? BackendClient.ServerMode : BackendClient.GameMode;
        UpdateModeUi();
    }

    private void UpdateModeUi()
    {
        var client = App.ApiClient;
        ModeLabelText.Text = client.ModeLabel;
        ModsNavItem.Content = client.IsServerMode ? "服务器 Mod" : "Mod 管理";
        var key = client.IsServerMode ? "ServerModeDotStyle" : "ClientModeDotStyle";
        ModeDot.Style = (Style)Application.Current.Resources[key];
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            Type? pageType = tag switch
            {
                "ModsPage" => typeof(Views.ModsPage),
                "SettingsPage" => typeof(Views.SettingsPage),
                _ => null
            };

            if (pageType != null && ContentFrame.CurrentSourcePageType != pageType)
            {
                ContentFrame.Navigate(pageType);
            }
        }
    }

    private async void CheckUpdateButton_Click(object sender, RoutedEventArgs e)
    {
        await CheckForUpdateAsync(silent: false);
    }

    public async Task CheckForUpdateAsync(bool silent)
    {
        if (_updateFlowActive)
        {
            return;
        }

        _updateFlowActive = true;
        CheckUpdateButton.IsEnabled = false;
        UpdateStatusText.Text = "正在检查更新...";

        try
        {
            var result = await App.ApiClient.CheckUpdateAsync();
            if (!result.Ok)
            {
                UpdateStatusText.Text = "更新检查失败";
                if (!silent)
                {
                    await ShowMessageAsync("检查更新", $"更新检查失败。\n\n原因：{result.Error}");
                }
                return;
            }

            if (!result.HasUpdate)
            {
                UpdateStatusText.Text = $"已是最新版本 ({result.CurrentVersion})";
                if (!silent)
                {
                    await ShowMessageAsync("检查更新", $"已是最新版本 ({result.CurrentVersion})。");
                }
                return;
            }

            var info = result.Update!;
            UpdateStatusText.Text = $"有可用版本: {info.Version}";
            if (silent)
            {
                return;
            }

            var notes = string.IsNullOrEmpty(info.Notes) ? string.Empty : $"\n\n更新内容:\n{info.Notes}";
            var confirm = new ContentDialog
            {
                XamlRoot = DialogRoot,
                Title = "发现新版本",
                Content = $"发现新版本: {info.Version}\n当前版本: {result.CurrentVersion}{notes}\n\n是否现在下载？\n更新后应用会自动关闭并重启。",
                PrimaryButtonText = "下载",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Primary,
            };
            if (await confirm.ShowAsync() != ContentDialogResult.Primary)
            {
                return;
            }

            string? downloadedPath;
            try
            {
                downloadedPath = await BusyDialog.RunWithProgressAsync<string?>(
                    DialogRoot,
                    $"正在下载新版本 {info.Version}...\n更新后应用会自动关闭并重启。",
                    progress => App.ApiClient.DownloadUpdateWithProgressAsync(progress));
            }
            catch (System.Exception ex)
            {
                UpdateStatusText.Text = "下载失败";
                await ShowMessageAsync("下载更新", $"下载失败。\n\n原因：{ex.Message}");
                return;
            }

            if (string.IsNullOrEmpty(downloadedPath))
            {
                UpdateStatusText.Text = "下载失败";
                await ShowMessageAsync("下载更新", "下载未完成，请重试。");
                return;
            }

            if (!IsLikelyInstaller(downloadedPath))
            {
                UpdateStatusText.Text = "下载文件无效";
                await ShowMessageAsync("下载更新", $"下载到的文件不是有效的安装程序，已停止安装。\n\n文件位置：{downloadedPath}");
                return;
            }

            UpdateStatusText.Text = $"正在安装 {info.Version}... 完成后自动重启";
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo(downloadedPath,
                    "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS")
                {
                    UseShellExecute = true
                };
                System.Diagnostics.Process.Start(psi);
                Microsoft.UI.Xaml.Application.Current.Exit();
            }
            catch (System.Exception ex)
            {
                UpdateStatusText.Text = "安装启动失败";
                await ShowMessageAsync("安装更新", $"无法启动安装程序。\n\n原因：{ex.Message}\n\n文件位置：{downloadedPath}");
            }
        }
        finally
        {
            _updateFlowActive = false;
            CheckUpdateButton.IsEnabled = true;
        }
    }

    private async Task ShowMessageAsync(string title, string content)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = DialogRoot,
            Title = title,
            Content = content,
            CloseButtonText = "关闭",
        };
        await dialog.ShowAsync();
    }

    private static bool IsLikelyInstaller(string path)
    {
        try
        {
            if (new FileInfo(path).Length < 1024 * 1024)
            {
                return false;
            }

            using var stream = File.OpenRead(path);
            return stream.ReadByte() == 'M' && stream.ReadByte() == 'Z';
        }
        catch (System.Exception)
        {
            return false;
        }
    }
}
