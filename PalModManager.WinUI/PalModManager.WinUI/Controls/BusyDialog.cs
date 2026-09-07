using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System;
using System.Threading.Tasks;

namespace PalModManager.WinUI.Controls;

public static class BusyDialog
{
    public static async Task<T?> RunAsync<T>(XamlRoot xamlRoot, string message, Func<Task<T>> action)
    {
        var panel = new StackPanel
        {
            MinWidth = 280,
            Children =
            {
                new TextBlock
                {
                    Text = message,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 12),
                },
                new ProgressBar
                {
                    IsIndeterminate = true,
                    Width = 260,
                },
            },
        };

        var dialog = new ContentDialog
        {
            XamlRoot = xamlRoot,
            Content = panel,
            PrimaryButtonText = null,
            SecondaryButtonText = null,
            CloseButtonText = null,
        };

        _ = dialog.ShowAsync();
        try
        {
            return await action();
        }
        finally
        {
            dialog.Hide();
        }
    }

    public static async Task RunAsync(XamlRoot xamlRoot, string message, Func<Task> action)
    {
        await RunAsync<object?>(xamlRoot, message, async () =>
        {
            await action();
            return null;
        });
    }

    public static async Task<T?> RunWithProgressAsync<T>(
        XamlRoot xamlRoot,
        string message,
        Func<IProgress<double>, Task<T>> action)
    {
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Width = 280, Margin = new Thickness(0, 0, 0, 4) };
        var percent = new TextBlock
        {
            Text = "0%",
            FontSize = 12,
            Opacity = 0.7,
            HorizontalAlignment = HorizontalAlignment.Right,
        };

        var panel = new StackPanel { MinWidth = 280 };
        panel.Children.Add(new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12),
        });
        panel.Children.Add(bar);
        panel.Children.Add(percent);

        var progress = new Progress<double>(ratio =>
        {
            var value = Math.Clamp(ratio, 0, 1) * 100;
            bar.Value = value;
            percent.Text = $"{value:F0}%";
        });

        var dialog = new ContentDialog
        {
            XamlRoot = xamlRoot,
            Content = panel,
            PrimaryButtonText = null,
            SecondaryButtonText = null,
            CloseButtonText = null,
        };

        _ = dialog.ShowAsync();
        try
        {
            return await action(progress);
        }
        finally
        {
            dialog.Hide();
        }
    }
}