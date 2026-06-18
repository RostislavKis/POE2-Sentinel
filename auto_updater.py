"""
POE2 Sentinel - Auto Updater

Checks GitHub Releases for updates and performs in-place exe replacement.
"""

import os
import sys
import json
import tempfile
import subprocess
import threading
import urllib.request
import urllib.error
from typing import Optional, Callable, Tuple
from dataclasses import dataclass

from version import VERSION

# GitHub info
GITHUB_REPO = "RostislavKis/POE2-Sentinel"
RELEASE_ASSET_NAME = "POE2Sentinel.exe"

@dataclass
class ReleaseInfo:
    """Information about a GitHub release."""
    version: str
    download_url: str
    release_notes: str
    published_at: str


def get_current_version() -> str:
    """Get current application version."""
    return VERSION


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse version string to tuple for comparison. Handles 'v1.0.0' or '1.0.0'."""
    v = version_str.lstrip('v')
    try:
        return tuple(int(x) for x in v.split('.'))
    except ValueError:
        return (0, 0, 0)


def check_for_updates() -> Optional[ReleaseInfo]:
    """
    Check GitHub Releases API for a newer version.
    Returns ReleaseInfo if update available, None otherwise.
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    try:
        req = urllib.request.Request(api_url, headers={
            'User-Agent': f'POE2Sentinel/{VERSION}',
            'Accept': 'application/vnd.github.v3+json'
        })

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        latest_version = data.get('tag_name', '').lstrip('v')
        if not latest_version:
            return None

        # Compare versions
        current = parse_version(VERSION)
        latest = parse_version(latest_version)

        if latest <= current:
            return None  # No update needed

        # Find the exe asset
        download_url = None
        for asset in data.get('assets', []):
            if asset.get('name') == RELEASE_ASSET_NAME:
                download_url = asset.get('browser_download_url')
                break

        if not download_url:
            return None  # No exe found in release

        return ReleaseInfo(
            version=latest_version,
            download_url=download_url,
            release_notes=data.get('body', ''),
            published_at=data.get('published_at', '')
        )

    except urllib.error.HTTPError as e:
        # 404 = no releases yet, not an error
        if e.code == 404:
            return None
        # Other HTTP errors - silent fail
        return None

    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        # Network error or bad response - silent fail
        return None


def download_update(release: ReleaseInfo, progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[str]:
    """
    Download the update to a temp file.
    Returns path to downloaded file, or None on failure.
    progress_callback(bytes_downloaded, total_bytes) is called during download.
    """
    try:
        req = urllib.request.Request(release.download_url, headers={
            'User-Agent': f'POE2Sentinel/{VERSION}'
        })
        
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"POE2Sentinel_v{release.version}.exe")
        
        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)
        
        return temp_path
        
    except Exception as e:
        print(f"Download failed: {e}")
        return None


def apply_update(new_exe_path: str) -> bool:
    """
    Apply the update by creating a PowerShell script that:
    1. Waits for current process to exit
    2. Replaces the exe
    3. Launches the new version

    Returns True if the updater script was launched successfully.
    """
    if not os.path.exists(new_exe_path):
        return False

    # Get current exe path
    if getattr(sys, 'frozen', False):
        current_exe = sys.executable
    else:
        # Running from Python - can't do in-place update
        print("In-place update only works with compiled exe")
        return False

    current_pid = os.getpid()

    # Create PowerShell updater script
    updater_script = f'''
# POE2 Sentinel Updater Script
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "POE2 Sentinel Updater"

Write-Host "================================"
Write-Host "  POE2 Sentinel Auto-Updater"
Write-Host "================================"
Write-Host ""

# Wait for the main process to exit
$processId = {current_pid}
$timeout = 30
$elapsed = 0

Write-Host "Waiting for POE2 Sentinel to close..."
while ($elapsed -lt $timeout) {{
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) {{
        break
    }}
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
}}

if ($elapsed -ge $timeout) {{
    Write-Host "Timeout waiting for process to exit. Update cancelled."
    pause
    exit 1
}}

# Wait for file handles to be released
Write-Host "Finalizing..."
Start-Sleep -Seconds 2

# Clean up PyInstaller temp folders (_MEI*) to prevent DLL conflicts
Write-Host "Cleaning up temporary files..."
$tempPath = [System.IO.Path]::GetTempPath()
$cleaned = 0
Get-ChildItem -Path $tempPath -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue | ForEach-Object {{
    try {{
        Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Cleaned: $($_.Name)"
        $cleaned++
    }} catch {{
        # Ignore errors - folder might be in use by another app
    }}
}}
if ($cleaned -eq 0) {{
    Write-Host "  No temp folders to clean"
}}

# Wait for filesystem to fully release handles
Write-Host "Waiting for system to settle..."
Start-Sleep -Seconds 3

# Replace the exe
$newExe = "{new_exe_path.replace(chr(92), chr(92)+chr(92))}"
$currentExe = "{current_exe.replace(chr(92), chr(92)+chr(92))}"

Write-Host "Installing update..."
try {{
    # Remove old exe first to ensure clean replacement
    if (Test-Path $currentExe) {{
        Remove-Item -Path $currentExe -Force
    }}

    # Copy new exe
    Copy-Item -Path $newExe -Destination $currentExe -Force
    Write-Host ""
    Write-Host "[OK] Update installed successfully!"

    # Clean up temp file
    Remove-Item -Path $newExe -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "================================"
    Write-Host "  Please launch POE2 Sentinel"
    Write-Host "  manually to use the new version."
    Write-Host "================================"
    Write-Host ""
    Write-Host "Press any key to close this window..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

}} catch {{
    Write-Host ""
    Write-Host "Update failed: $_"
    Write-Host ""
    Write-Host "The new version is saved at: $newExe"
    Write-Host "You can manually replace the exe."
    Write-Host ""
    pause
    exit 1
}}
'''

    # Save script to temp
    script_path = os.path.join(tempfile.gettempdir(), "poe2sentinel_updater.ps1")
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(updater_script)

    # Launch PowerShell script (visible window so user sees progress)
    try:
        subprocess.Popen(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-File', script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
        )
        return True
    except Exception as e:
        print(f"Failed to launch updater: {e}")
        return False


def check_and_prompt_update(parent_window=None, on_complete: Optional[Callable[[bool, str], None]] = None):
    """
    Check for updates in background thread and call on_complete when done.
    on_complete(update_available: bool, message: str)
    """
    def _check():
        release = check_for_updates()
        if release:
            msg = f"Version {release.version} is available!\n\nRelease notes:\n{release.release_notes[:500]}"
            if on_complete:
                on_complete(True, msg, release)
        else:
            if on_complete:
                on_complete(False, "You're running the latest version.", None)

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()
