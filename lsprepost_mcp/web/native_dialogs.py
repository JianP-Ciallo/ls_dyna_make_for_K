from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Optional


class NativeDialogUnavailable(RuntimeError):
    pass


_DIALOG_LOCK = threading.Lock()
_DIALOG_TIMEOUT_S = 2 * 60
_WINDOWS_DIALOG_SCRIPT = r"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$owner = New-Object System.Windows.Forms.Form
$owner.Text = "lsprepost-mcp"
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$owner.Size = New-Object System.Drawing.Size(2, 2)
$owner.Opacity = 0.01

try {
    $owner.Show()
    [System.Windows.Forms.Application]::DoEvents()
    $owner.BringToFront()
    $owner.Activate()

    if ($env:LSPP_PICKER_MODE -eq "directory") {
        $shell = $null
        $folder = $null
        try {
            $shell = New-Object -ComObject Shell.Application
            $flags = 0x00000001 -bor 0x00000010 -bor 0x00000040
            $rootFolder = 0
            $folder = $shell.BrowseForFolder(
                $owner.Handle.ToInt64(),
                $env:LSPP_PICKER_TITLE,
                $flags,
                $rootFolder
            )
            if ($null -ne $folder) {
                $selectedPath = [string]$folder.Self.Path
                if (-not [string]::IsNullOrWhiteSpace($selectedPath)) {
                    [Console]::Out.Write($selectedPath)
                }
            }
        }
        catch {
            $dialog = New-Object System.Windows.Forms.OpenFileDialog
            $dialog.Title = $env:LSPP_PICKER_TITLE
            $dialog.FileName = "Select this folder"
            $dialog.Filter = "Folder|*.folder"
            $dialog.CheckFileExists = $false
            $dialog.CheckPathExists = $true
            $dialog.ValidateNames = $false
            $dialog.Multiselect = $false
            $dialog.RestoreDirectory = $true
            $initialDirectory = [Environment]::GetFolderPath(
                [Environment+SpecialFolder]::MyDocuments
            )
            if ([System.IO.Directory]::Exists($initialDirectory)) {
                $dialog.InitialDirectory = $initialDirectory
            }
            $result = $dialog.ShowDialog($owner)
            if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
                $selectedPath = [System.IO.Path]::GetDirectoryName($dialog.FileName)
                if (-not [string]::IsNullOrWhiteSpace($selectedPath)) {
                    [Console]::Out.Write($selectedPath)
                }
            }
        }
        finally {
            if ($null -ne $folder) {
                [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($folder)
            }
            if ($null -ne $shell) {
                [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
            }
        }
    }
    else {
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = $env:LSPP_PICKER_TITLE
        $dialog.Filter = $env:LSPP_PICKER_FILTER
        $dialog.CheckFileExists = $true
        $dialog.CheckPathExists = $true
        $dialog.Multiselect = $false
        $dialog.RestoreDirectory = $true
        $result = $dialog.ShowDialog($owner)
        if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
            [Console]::Out.Write($dialog.FileName)
        }
    }
}
finally {
    $owner.Close()
    $owner.Dispose()
}
"""


def _run_windows_picker(
    *,
    mode: str,
    title: str,
    filetypes: list[tuple[str, str]] | None = None,
) -> Optional[Path]:
    if mode not in {"directory", "file"}:
        raise ValueError(f"unsupported native picker mode: {mode}")

    env = os.environ.copy()
    env["LSPP_PICKER_MODE"] = mode
    env["LSPP_PICKER_TITLE"] = title
    env["LSPP_PICKER_FILTER"] = "|".join(
        item for pair in (filetypes or [("All files", "*.*")]) for item in pair
    )
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        _WINDOWS_DIALOG_SCRIPT,
    ]

    with _DIALOG_LOCK:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=_DIALOG_TIMEOUT_S,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except FileNotFoundError as exc:
            raise NativeDialogUnavailable("无法启动 Windows PowerShell 文件选择窗口") from exc
        except subprocess.TimeoutExpired as exc:
            raise NativeDialogUnavailable("系统文件选择窗口等待超时") from exc
        except OSError as exc:
            raise NativeDialogUnavailable("无法启动系统文件选择窗口") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Windows 文件选择窗口启动失败"
        raise NativeDialogUnavailable(detail)

    selected = completed.stdout.strip()
    return Path(selected) if selected else None


def choose_directory(title: str) -> Optional[Path]:
    return _run_windows_picker(mode="directory", title=title)


def choose_file(title: str, filetypes: list[tuple[str, str]]) -> Optional[Path]:
    return _run_windows_picker(mode="file", title=title, filetypes=filetypes)
