using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PalModManager.WinUI.Services;
using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace PalModManager.WinUI.Views;

public sealed partial class ProfileDialog : ContentDialog
{
    private readonly BackendClient _client = App.ApiClient;
    private List<ProfileDto> _profiles = new();

    private ProfileDialog()
    {
        this.InitializeComponent();
        Title = $"Mod 方案管理（{_client.ModeLabel}）";
        ScopeText.Text =
            $"方案按{_client.ModeLabel}安装目录分别保存，切换到另一种模式会看到另一套方案。";
    }

    public string? LoadedProfileName { get; private set; }

    /// <summary>
    /// Opens the manager and returns the profile name the user asked to load;
    /// create and delete are applied immediately inside the dialog.
    /// </summary>
    public static async Task<string?> ShowManageAsync(XamlRoot xamlRoot)
    {
        var dialog = new ProfileDialog { XamlRoot = xamlRoot };
        await dialog.RefreshAsync();
        var result = await dialog.ShowAsync();
        return result == ContentDialogResult.Primary ? dialog.LoadedProfileName : null;
    }

    private string? SelectedName =>
        ProfilesList.SelectedIndex >= 0 && ProfilesList.SelectedIndex < _profiles.Count
            ? _profiles[ProfilesList.SelectedIndex].Name
            : null;

    private async Task RefreshAsync()
    {
        try
        {
            _profiles = await _client.GetProfilesAsync();
            HideStatus();
        }
        catch (Exception ex)
        {
            _profiles = new List<ProfileDto>();
            ShowStatus($"读取方案失败：{ex.Message}", isError: true);
        }

        ProfilesList.Items.Clear();
        foreach (var profile in _profiles)
        {
            ProfilesList.Items.Add($"{profile.Name}（{profile.EnabledMods.Count} 个 Mod）");
        }

        ProfilesList.SelectedIndex = -1;
        DeleteButton.IsEnabled = false;
    }

    private void ProfilesList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var name = SelectedName;
        DeleteButton.IsEnabled = name != null;
        if (name != null)
        {
            NewNameBox.Text = name;
        }
    }

    private async void CreateButton_Click(object sender, RoutedEventArgs e)
    {
        var name = NewNameBox.Text.Trim();
        if (name.Length == 0)
        {
            ShowStatus("请先填写方案名称。", isError: true);
            return;
        }

        try
        {
            await _client.CreateProfileAsync(name, NewDescBox.Text.Trim());
            NewNameBox.Text = string.Empty;
            NewDescBox.Text = string.Empty;
            await RefreshAsync();
            ShowStatus($"已保存方案 {name}。", isError: false);
        }
        catch (Exception ex)
        {
            ShowStatus($"保存方案失败：{ex.Message}", isError: true);
        }
    }

    private async void DeleteButton_Click(object sender, RoutedEventArgs e)
    {
        var name = SelectedName;
        if (name is null)
        {
            ShowStatus("请先选择要删除的方案。", isError: true);
            return;
        }

        try
        {
            await _client.DeleteProfileAsync(name);
            await RefreshAsync();
            ShowStatus($"已删除方案 {name}。", isError: false);
        }
        catch (Exception ex)
        {
            ShowStatus($"删除方案失败：{ex.Message}", isError: true);
        }
    }

    private void PrimaryButtonClickHandler(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var name = SelectedName;
        if (name is null)
        {
            args.Cancel = true;
            ShowStatus("请先选择要加载的方案。", isError: true);
            return;
        }

        LoadedProfileName = name;
    }

    private void ShowStatus(string text, bool isError)
    {
        StatusText.Text = text;
        // WinUI 3 has no SetResourceReference, so pick the themed style instead.
        StatusText.Style = (Style)Application.Current.Resources[isError ? "ErrorTextStyle" : "SuccessTextStyle"];
        StatusText.Visibility = Visibility.Visible;
    }

    private void HideStatus()
    {
        StatusText.Visibility = Visibility.Collapsed;
    }
}
