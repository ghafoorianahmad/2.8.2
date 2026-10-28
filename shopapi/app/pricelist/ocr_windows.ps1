# v2.14.0: text of a picture with the OCR that is built into Windows 10/11
# (Windows.Media.Ocr, nothing to install). Prints one JSON object:
#   {"lang": "en-US", "width": W, "height": H,
#    "lines": [{"text": "...", "words": [{"t": "...", "x": .., "y": .., "w": .., "h": ..}]}]}
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File ocr_windows.ps1 <image> [scale]
param([Parameter(Mandatory = $true)][string]$Path, [double]$Scale = 1.0)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Path).Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$transform = New-Object Windows.Graphics.Imaging.BitmapTransform
$max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
$w = [double]$decoder.PixelWidth * $Scale; $h = [double]$decoder.PixelHeight * $Scale
$fit = [Math]::Min(1.0, [Math]::Min($max / $w, $max / $h))
$transform.ScaledWidth = [uint32]($w * $fit); $transform.ScaledHeight = [uint32]($h * $fit)
$transform.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
$bitmap = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $transform,
    [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
$lang = [Windows.Globalization.Language]::new('en-US')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) { Write-Output '{"error": "no OCR language"}'; exit 2 }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$k = 1.0 / ($Scale * $fit)
$lines = foreach ($line in $result.Lines) {
    $words = foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        [ordered]@{ t = $word.Text; x = [int]($r.X * $k); y = [int]($r.Y * $k);
                    w = [int]($r.Width * $k); h = [int]($r.Height * $k) }
    }
    [ordered]@{ text = $line.Text; words = @($words) }
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[ordered]@{ lang = $engine.RecognizerLanguage.LanguageTag; width = [int]$decoder.PixelWidth;
            height = [int]$decoder.PixelHeight; lines = @($lines) } | ConvertTo-Json -Depth 6 -Compress
