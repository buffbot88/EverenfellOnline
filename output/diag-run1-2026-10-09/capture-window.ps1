Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WinRect {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
}
"@
$p = Get-Process -Name flashplayer363 | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$r = New-Object WinRect+RECT
[WinRect]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
$out = Join-Path (Get-Location) 'projector-window.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$dark = 0; $tot = 0; $sum = 0
for ($x = 0; $x -lt $w; $x += 16) { for ($y = 0; $y -lt $h; $y += 16) {
  $c = $bmp.GetPixel($x, $y); $tot++; $sum += ($c.R + $c.G + $c.B) / 3
  if (($c.R + $c.G + $c.B) -lt 60) { $dark++ } } }
"size=${w}x${h} dark_fraction=$([math]::Round($dark/$tot,3)) mean_luma=$([math]::Round($sum/$tot,1)) saved=$out"
$g.Dispose(); $bmp.Dispose()
