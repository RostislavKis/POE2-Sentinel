"""
POE2 Sentinel - Auto Updater

Checks GitHub Releases for updates and performs a safe, integrity-verified,
rollback-protected in-place replacement of the running executable.
"""

import os
import sys
import json
import shutil
import hashlib
import logging
import tempfile
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Callable, Tuple
from dataclasses import dataclass

from version import VERSION

logger = logging.getLogger("poe2sentinel.updater")

# GitHub info
GITHUB_REPO = "RostislavKis/POE2-Sentinel"
RELEASE_ASSET_NAME = "POE2Sentinel.exe"

# Network / IO tuning
_API_TIMEOUT = 10        # seconds
_DOWNLOAD_TIMEOUT = 60   # seconds
_CHUNK_SIZE = 64 * 1024  # bytes


@dataclass
class ReleaseInfo:
    """Information about a GitHub release."""
    version: str
    download_url: str
    release_notes: str
    published_at: str
    sha256: Optional[str] = None   # expected lowercase hex digest, if published
    size: int = 0                  # expected asset size in bytes, 0 if unknown


def get_current_version() -> str:
    """Get the current application version."""
    return VERSION


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse a version string to a comparable tuple. Handles 'v1.0.0' or '1.0.0'."""
    v = (version_str or "").lstrip("v")
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0, 0, 0)


def _parse_digest(asset: dict) -> Optional[str]:
    """Extract a lowercase sha256 hex digest from a GitHub asset, if present."""
    digest = asset.get("digest") or ""
    if digest.lower().startswith("sha256:"):
        return digest.split(":", 1)[1].strip().lower() or None
    return None


def check_for_updates() -> Optional[ReleaseInfo]:
    """
    Check the GitHub Releases API for a newer version.
    Returns ReleaseInfo if an update is available, None otherwise.
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={
            "User-Agent": f"POE2Sentinel/{VERSION}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))

        latest_version = (data.get("tag_name") or "").lstrip("v")
        if not latest_version:
            return None

        if parse_version(latest_version) <= parse_version(VERSION):
            return None  # already up to date

        asset = next((a for a in data.get("assets", [])
                      if a.get("name") == RELEASE_ASSET_NAME), None)
        if not asset or not asset.get("browser_download_url"):
            logger.info("No '%s' asset in latest release %s", RELEASE_ASSET_NAME, latest_version)
            return None

        return ReleaseInfo(
            version=latest_version,
            download_url=asset["browser_download_url"],
            release_notes=data.get("body", "") or "",
            published_at=data.get("published_at", "") or "",
            sha256=_parse_digest(asset),
            size=int(asset.get("size") or 0),
        )

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # no releases yet
        logger.warning("Update check failed (HTTP %s)", e.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Update check failed (network): %s", e)
        return None
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Update check failed (bad response): %s", e)
        return None


def download_update(release: ReleaseInfo,
                    progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[str]:
    """
    Download the update into a freshly-created private temp directory and verify
    its integrity (exact byte count, and SHA-256 when the release publishes one).

    Returns the path to the verified file, or None on any failure. Partial or
    corrupt downloads are deleted before returning.
    """
    work_dir = tempfile.mkdtemp(prefix="poe2sentinel_upd_")
    temp_path = os.path.join(work_dir, RELEASE_ASSET_NAME)
    ok = False
    try:
        req = urllib.request.Request(release.download_url, headers={
            "User-Agent": f"POE2Sentinel/{VERSION}",
        })
        hasher = hashlib.sha256()
        downloaded = 0
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as response:
            total_size = int(response.headers.get("Content-Length") or release.size or 0)
            with open(temp_path, "wb") as f:
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        # Integrity check 1: exact size.
        if total_size and downloaded != total_size:
            logger.error("Download size mismatch: got %d of %d bytes", downloaded, total_size)
            return None

        # Integrity check 2: SHA-256 (only possible when the release publishes one).
        if release.sha256:
            actual = hasher.hexdigest()
            if actual != release.sha256:
                logger.error("Checksum mismatch: expected %s, got %s", release.sha256, actual)
                return None
        else:
            logger.warning("Release %s has no published SHA-256; size-verified only", release.version)

        ok = True
        return temp_path

    except Exception as e:
        logger.error("Download failed: %s", e)
        return None
    finally:
        if not ok:
            shutil.rmtree(work_dir, ignore_errors=True)


def _ps_single_quote(s: str) -> str:
    """Quote a string as a PowerShell single-quoted literal (no $/backtick expansion)."""
    return "'" + s.replace("'", "''") + "'"


def apply_update(new_exe_path: str) -> bool:
    """
    Apply the update via a helper PowerShell script that waits for this process to
    exit, then performs an atomic, rollback-safe replacement of the running exe
    (move-aside + copy + restore-on-failure, with bounded retries for file locks).

    The new version must be launched manually afterwards. Auto-relaunch was
    intentionally removed to avoid PyInstaller `_MEI*` extraction conflicts.

    Returns True if the updater script was launched successfully.
    """
    if not os.path.isfile(new_exe_path):
        return False
    if not getattr(sys, "frozen", False):
        logger.info("In-place update only works with the compiled exe")
        return False

    current_exe = sys.executable
    current_pid = os.getpid()

    # Paths are emitted as PowerShell single-quoted literals, which neutralises
    # any $/backtick/subexpression injection regardless of their content.
    new_exe_q = _ps_single_quote(new_exe_path)
    current_exe_q = _ps_single_quote(current_exe)

    updater_script = f'''# POE2 Sentinel Updater
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "POE2 Sentinel Updater"
$processId = {current_pid}
$newExe = {new_exe_q}
$currentExe = {current_exe_q}
$backup = "$currentExe.old"

Write-Host "================================"
Write-Host "  POE2 Sentinel Auto-Updater"
Write-Host "================================"
Write-Host ""

Write-Host "Waiting for POE2 Sentinel to close..."
$elapsed = 0.0
while ($elapsed -lt 30) {{
    if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
}}
if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {{
    Write-Host "Timeout waiting for process to exit. Update cancelled."
    pause
    exit 1
}}

# Allow file handles to settle.
Start-Sleep -Seconds 1

Write-Host "Cleaning up temporary files..."
$tempPath = [System.IO.Path]::GetTempPath()
Get-ChildItem -Path $tempPath -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue | ForEach-Object {{
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
}}

Write-Host "Installing update..."
$installed = $false
for ($attempt = 1; $attempt -le 5 -and -not $installed; $attempt++) {{
    try {{
        if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force }}
        Move-Item -LiteralPath $currentExe -Destination $backup -Force
        try {{
            Copy-Item -LiteralPath $newExe -Destination $currentExe -Force
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
            $installed = $true
        }} catch {{
            # Roll back: restore the original executable, then re-raise.
            if (Test-Path -LiteralPath $currentExe) {{ Remove-Item -LiteralPath $currentExe -Force -ErrorAction SilentlyContinue }}
            Move-Item -LiteralPath $backup -Destination $currentExe -Force
            throw
        }}
    }} catch {{
        if ($attempt -ge 5) {{
            Write-Host ""
            Write-Host "Update failed: $_"
            Write-Host "Your installation was restored. The new version is at: $newExe"
            pause
            exit 1
        }}
        Start-Sleep -Seconds 2
    }}
}}

# Best-effort cleanup of the downloaded file and its private temp dir.
Remove-Item -LiteralPath $newExe -Force -ErrorAction SilentlyContinue
try {{ Remove-Item -LiteralPath (Split-Path -Parent $newExe) -Recurse -Force -ErrorAction SilentlyContinue }} catch {{}}

Write-Host ""
Write-Host "================================"
Write-Host "  [OK] Update installed."
Write-Host "  Please launch POE2 Sentinel manually."
Write-Host "================================"
Write-Host ""
Write-Host "Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
'''

    try:
        script_dir = tempfile.mkdtemp(prefix="poe2sentinel_updscript_")
        script_path = os.path.join(script_dir, "updater.ps1")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(updater_script)

        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )
        return True
    except Exception as e:
        logger.error("Failed to launch updater: %s", e)
        return False
