using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PalModManager.WinUI.Services;
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
        Func<IProgress<ByteProgress>, Task<T>> action)
    {
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Width = 300, Margin = new Thickness(0, 0, 0, 4) };
        var detail = new TextBlock
        {
            Text = "0 MB",
            FontSize = 12,
            Opacity = 0.7,
            HorizontalAlignment = HorizontalAlignment.Right,
        };

        var panel = new StackPanel { MinWidth = 300 };
        panel.Children.Add(new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12),
        });
        panel.Children.Add(bar);
        panel.Children.Add(detail);

        const double Mb = 1024d * 1024d;
        var sampleTime = DateTime.UtcNow;
        long sampleBytes = 0;
        double bytesPerSec = 0;
        bool hasRate = false;

        var progress = new Progress<ByteProgress>(value =>
        {
            var now = DateTime.UtcNow;
            var elapsed = (now - sampleTime).TotalSeconds;
            if (elapsed >= 0.5)
            {
                var instant = Math.Max(0, (value.Done - sampleBytes) / elapsed);
                bytesPerSec = hasRate ? bytesPerSec * 0.4 + instant * 0.6 : instant;
                hasRate = true;
                sampleTime = now;
                sampleBytes = value.Done;
            }

            bar.Value = value.Ratio * 100;
            var size = value.Total > 0
                ? $"{value.Done / Mb:F1} / {value.Total / Mb:F1} MB ({value.Ratio * 100:F0}%)"
                : $"{value.Done / Mb:F1} MB";
            detail.Text = hasRate ? $"{size}  {FormatRate(bytesPerSec)}" : size;
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

    private static string FormatRate(double bytesPerSec)
        => bytesPerSec >= 1024d * 1024d
            ? $"{bytesPerSec / (1024d * 1024d):F1} MB/s"
            : $"{bytesPerSec / 1024d:F0} KB/s";
}