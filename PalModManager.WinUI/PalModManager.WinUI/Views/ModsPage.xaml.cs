using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using PalModManager.Core.Models;
using PalModManager.WinUI.Controls;
using PalModManager.WinUI.Services;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace PalModManager.WinUI.Views;

public sealed partial class ModsPage : Page
{
    public ModsViewModel ViewModel { get; } = new ModsViewModel();

    public ModsPage()
    {
        this.InitializeComponent();
        this.DataContext = ViewModel;
        ViewModel.ErrorRaised += ShowError;
        ViewModel.SuccessRaised += ShowSuccess;
        ViewModel.Reloaded += ClearDetail;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        App.ApiClient.ModeChanged += OnModeChanged;
        UpdateModeLabels();
        await ViewModel.LoadAsync();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        App.ApiClient.ModeChanged -= OnModeChanged;
    }

    private async void OnModeChanged()
    {
        UpdateModeLabels();
        await ViewModel.LoadAsync();
    }

    private void UpdateModeLabels()
    {
        var isServer = App.ApiClient.IsServerMode;
        ModListHeaderText.Text = isServer ? "服务器 Mod 列表" : "Mod 列表";
        LaunchButton.Content = isServer ? "启动服务器" : "启动游戏";
    }

    private bool _splitterDragging;
    private double _splitterStartX;
    private double _splitterStartWidth;

    private void SplitterHandle_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        _splitterDragging = true;
        _splitterStartX = e.GetCurrentPoint(LayoutGrid).Position.X;
        _splitterStartWidth = LayoutGrid.ColumnDefinitions[0].ActualWidth;
        SplitterHandle.CapturePointer(e.Pointer);
    }

    private void SplitterHandle_PointerMoved(object sender, PointerRoutedEventArgs e)
    {
        if (!_splitterDragging)
        {
            return;
        }

        var x = e.GetCurrentPoint(LayoutGrid).Position.X;
        var width = Math.Clamp(
            _splitterStartWidth + (x - _splitterStartX),
            300,
            Math.Max(300, LayoutGrid.ActualWidth - 420));
        LayoutGrid.ColumnDefinitions[0].Width = new GridLength(width);
    }

    private void SplitterHandle_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        _splitterDragging = false;
        SplitterHandle.ReleasePointerCapture(e.Pointer);
    }

    private void ClearDetail()
    {
        ModsListView.SelectedItem = null;
        DetailName.Text = string.Empty;
        DetailType.Text = string.Empty;
        DetailStatus.Text = string.Empty;
        DetailDescription.Text = string.Empty;
        DetailPath.Text = string.Empty;
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

    private void SearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        ViewModel.FilterText = args.QueryText ?? string.Empty;
    }

    private void Filter_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        ViewModel.TypeFilter = TypeFilter.SelectedItem?.ToString() ?? string.Empty;
        ViewModel.StatusFilter = StatusFilter.SelectedItem?.ToString() ?? string.Empty;
    }

    private void ModsListView_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ModsListView.SelectedItem is ModInfo mod)
        {
            DetailName.Text = mod.Name;
            DetailType.Text = mod.ModType.ToString();
            DetailStatus.Text = mod.Status.ToString();
            DetailDescription.Text = mod.Description;
            DetailPath.Text = mod.InstallPath;
        }
    }

    private async void EnableCheckBox_Click(object sender, RoutedEventArgs e)
    {
        if (sender is CheckBox checkBox && checkBox.DataContext is ModInfo mod)
        {
            await ViewModel.ToggleModAsync(mod);
        }
    }

    private async void EnableAllButton_Click(object sender, RoutedEventArgs e)
    {
        await BusyDialog.RunAsync(this.XamlRoot, "正在启用全部 Mod...", () => ViewModel.EnableAllAsync());
    }

    private async void DisableAllButton_Click(object sender, RoutedEventArgs e)
    {
        await BusyDialog.RunAsync(this.XamlRoot, "正在禁用全部 Mod...", () => ViewModel.DisableAllAsync());
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
    {
        var file = await PickFileAsync();
        if (!string.IsNullOrEmpty(file))
        {
            await BusyDialog.RunAsync(this.XamlRoot, "正在导入 Mod...", () => ViewModel.ImportAsync(file));
        }
    }

    private async void ExportButton_Click(object sender, RoutedEventArgs e)
    {
        var folder = await PickFolderAsync();
        if (!string.IsNullOrEmpty(folder))
        {
            await BusyDialog.RunAsync(this.XamlRoot, "正在导出 Mod...", () => ViewModel.ExportAsync(folder));
        }
    }

    private async void ScanButton_Click(object sender, RoutedEventArgs e)
    {
        var folder = await PickFolderAsync();
        if (!string.IsNullOrEmpty(folder))
        {
            await BusyDialog.RunAsync(this.XamlRoot, "正在扫描合集...", () => ViewModel.ScanCollectionAsync(folder));
        }
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e)
    {
        await ViewModel.LoadAsync();
    }

    private async void ProfileButton_Click(object sender, RoutedEventArgs e)
    {
        var loaded = await ProfileDialog.ShowManageAsync(this.XamlRoot);
        if (!string.IsNullOrEmpty(loaded))
        {
            await ViewModel.LoadProfileAsync(loaded!);
        }
    }

    private async void RepairButton_Click(object sender, RoutedEventArgs e)
    {
        await BusyDialog.RunAsync(this.XamlRoot, "正在检查并修复文件结构...", () => ViewModel.RepairAsync());
    }

    private async void LaunchButton_Click(object sender, RoutedEventArgs e)
    {
        await ViewModel.LaunchAsync();
    }

    private async void OpenFolderButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModsListView.SelectedItem is ModInfo mod && !string.IsNullOrEmpty(mod.InstallPath))
        {
            await Task.Run(() =>
            {
                try
                {
                    Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{mod.InstallPath}\"")
                    {
                        UseShellExecute = true,
                    });
                }
                catch
                {
                    // ignore
                }
            });
        }
    }

    private async void UninstallButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModsListView.SelectedItem is not ModInfo mod)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = this.XamlRoot,
            Title = "确认卸载",
            Content = $"确定要卸载 {mod.Name} 吗？",
            PrimaryButtonText = "卸载",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
        };
        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary)
        {
            await ViewModel.UninstallAsync(mod);
        }
    }

    private async Task<string?> PickFileAsync()
    {
        var window = App.MainWindowInstance;
        if (window is null)
        {
            return null;
        }

        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
        };
        picker.FileTypeFilter.Add(".zip");
        picker.FileTypeFilter.Add(".pak");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        return file?.Path;
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

public class ModsViewModel : INotifyPropertyChanged
{
    private readonly BackendClient _client;
    private readonly List<ModInfo> _allMods = new();
    private string _filterText = string.Empty;
    private string _typeFilter = string.Empty;
    private string _statusFilter = string.Empty;
    private string _statsText = string.Empty;
    private int _loadToken;

    public ModsViewModel()
    {
        _client = App.ApiClient;
        Mods = new ObservableCollection<ModInfo>();
    }

    public ObservableCollection<ModInfo> Mods { get; }

    public event Action<string>? ErrorRaised;

    public event Action? Reloaded;

    public event Action<string>? SuccessRaised;

    public string FilterText
    {
        get => _filterText;
        set
        {
            if (SetProperty(ref _filterText, value))
            {
                ApplyFilters();
            }
        }
    }

    public string TypeFilter
    {
        get => _typeFilter;
        set
        {
            if (SetProperty(ref _typeFilter, value))
            {
                ApplyFilters();
            }
        }
    }

    public string StatusFilter
    {
        get => _statusFilter;
        set
        {
            if (SetProperty(ref _statusFilter, value))
            {
                ApplyFilters();
            }
        }
    }

    public string StatsText
    {
        get => _statsText;
        private set => SetProperty(ref _statsText, value);
    }

    public async Task LoadAsync()
    {
        var token = ++_loadToken;
        if (!await _client.WaitUntilReadyAsync(TimeSpan.FromSeconds(10)))
        {
            _allMods.Clear();
            ApplyFilters();
            ErrorRaised?.Invoke("后端服务未就绪，请检查 Python 环境。");
            return;
        }

        try
        {
            var mods = await _client.GetModsAsync();
            if (token != _loadToken)
            {
                return;
            }

            _allMods.Clear();
            foreach (var mod in mods)
            {
                _allMods.Add(mod);
            }
            ApplyFilters();
            Reloaded?.Invoke();
        }
        catch (Exception ex)
        {
            if (token != _loadToken)
            {
                return;
            }

            _allMods.Clear();
            ApplyFilters();
            ErrorRaised?.Invoke($"加载 Mod 列表失败：{ex.Message}");
        }
    }

    public async Task ToggleModAsync(ModInfo mod)
    {
        try
        {
            await _client.ToggleModAsync(mod.Id);
            await LoadAsync();
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"切换 Mod 状态失败：{ex.Message}");
        }
    }

    public async Task EnableAllAsync()
    {
        try
        {
            await _client.EnableAllAsync();
            await LoadAsync();
            SuccessRaised?.Invoke("已启用全部 Mod。");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"全部启用失败：{ex.Message}");
        }
    }

    public async Task DisableAllAsync()
    {
        try
        {
            await _client.DisableAllAsync();
            await LoadAsync();
            SuccessRaised?.Invoke("已禁用全部 Mod。");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"全部禁用失败：{ex.Message}");
        }
    }

    public async Task LoadProfileAsync(string name)
    {
        try
        {
            await _client.LoadProfileAsync(name);
            await LoadAsync();
            SuccessRaised?.Invoke($"已加载方案 {name}。");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"加载方案失败：{ex.Message}");
        }
    }

    public async Task LaunchAsync()
    {
        try
        {
            var result = await _client.LaunchGameAsync();
            if (result?.Success == true)
            {
                SuccessRaised?.Invoke($"{_client.ModeLabel}已启动。");
            }
            else
            {
                ErrorRaised?.Invoke($"启动失败：{(string.IsNullOrEmpty(result?.Message) ? "未知错误" : result!.Message)}");
            }
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"启动失败：{ex.Message}");
        }
    }

    public async Task RepairAsync()
    {
        try
        {
            var result = await _client.RepairAsync();
            await LoadAsync();
            if (result is null)
            {
                ErrorRaised?.Invoke("修复失败。");
                return;
            }

            SuccessRaised?.Invoke(result.FixedCount == 0
                ? "文件结构正常，无需修复。"
                : $"已修复 {result.FixedCount} 处：" + string.Join("；", result.Messages.Take(3)));
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"修复失败：{ex.Message}");
        }
    }

    public async Task ImportAsync(string sourcePath)
    {
        try
        {
            var mod = await _client.ImportModAsync(sourcePath);
            await LoadAsync();
            SuccessRaised?.Invoke(mod is null ? "导入完成。" : $"已导入 {mod.Name}。");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"导入失败：{ex.Message}");
        }
    }

    public async Task ExportAsync(string outputDir)
    {
        try
        {
            var result = await _client.ExportModsAsync(outputDir);
            if (result is null)
            {
                ErrorRaised?.Invoke("导出失败。");
                return;
            }

            SuccessRaised?.Invoke(result.Errors.Count > 0
                ? $"已导出 {result.Count} 个 Mod，{result.Errors.Count} 个错误：{string.Join("；", result.Errors.Take(3))}"
                : $"已导出 {result.Count} 个 Mod 到 {result.Path}");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"导出失败：{ex.Message}");
        }
    }

    public async Task ScanCollectionAsync(string collectionDir)
    {
        try
        {
            var mods = await _client.ScanCollectionAsync(collectionDir);
            _allMods.Clear();
            foreach (var mod in mods)
            {
                _allMods.Add(mod);
            }
            ApplyFilters();
            SuccessRaised?.Invoke($"扫描完成，发现 {mods.Count} 个 Mod。");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"扫描合集失败：{ex.Message}");
        }
    }

    public async Task UninstallAsync(ModInfo mod)
    {
        try
        {
            var backupError = await _client.DeleteModAsync(mod.Id);
            await LoadAsync();
            SuccessRaised?.Invoke(string.IsNullOrEmpty(backupError)
                ? $"已卸载 {mod.Name}。"
                : $"已卸载 {mod.Name}，但备份失败：{backupError}");
        }
        catch (Exception ex)
        {
            ErrorRaised?.Invoke($"卸载失败：{ex.Message}");
        }
    }

    private void ApplyFilters()
    {
        Mods.Clear();
        var query = _allMods.AsEnumerable();

        if (!string.IsNullOrWhiteSpace(FilterText))
        {
            query = query.Where(m => m.Name.Contains(FilterText, StringComparison.OrdinalIgnoreCase));
        }

        if (!string.IsNullOrWhiteSpace(TypeFilter) && TypeFilter != "All")
        {
            query = query.Where(m => m.ModType.ToString().Equals(TypeFilter, StringComparison.OrdinalIgnoreCase));
        }

        if (!string.IsNullOrWhiteSpace(StatusFilter) && StatusFilter != "All")
        {
            var statusKey = StatusFilter switch
            {
                "已启用" => "ENABLED",
                "已禁用" => "DISABLED",
                "冲突" => "CONFLICT",
                _ => StatusFilter
            };
            query = query.Where(m => m.Status.ToString().Equals(statusKey, StringComparison.OrdinalIgnoreCase));
        }

        foreach (var mod in query)
        {
            Mods.Add(mod);
        }

        var enabled = _allMods.Count(m => m.Status == ModStatus.ENABLED);
        var disabled = _allMods.Count(m => m.Status == ModStatus.DISABLED);
        var conflict = _allMods.Count(m => m.Status == ModStatus.CONFLICT);
        var summary = $"共 {_allMods.Count} · 启用 {enabled} · 禁用 {disabled} · 冲突 {conflict}";
        StatsText = Mods.Count == _allMods.Count
            ? summary
            : $"{summary}（显示 {Mods.Count}）";
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string propertyName = null!)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }

    private bool SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = null!)
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
        {
            return false;
        }
        storage = value;
        OnPropertyChanged(propertyName);
        return true;
    }
}

public class ModStatusToBoolConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        return value is ModStatus status && status == ModStatus.ENABLED;
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language)
    {
        throw new NotImplementedException();
    }
}