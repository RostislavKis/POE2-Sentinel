"""POE2 Sentinel - Build Script.

Builds the executable with PyInstaller and creates an installer with Inno Setup.
Run from anywhere: py build/build_exe.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = Path(__file__).resolve().parent
SPEC_FILE = BUILD_DIR / "POE2Sentinel.spec"
DIST_APP = PROJECT_ROOT / "dist" / "POE2Sentinel"
EXE_PATH = DIST_APP / "POE2Sentinel.exe"


def header(text: str) -> None:
    print("\n" + "=" * 70 + f"\n  {text}\n" + "=" * 70 + "\n")


def ensure_pyinstaller() -> bool:
    header("Checking PyInstaller")
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
        return True
    except ImportError:
        print("[INFO] Installing PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            return True
        except subprocess.CalledProcessError:
            print("[ERROR] Failed to install PyInstaller.")
            return False


def install_dependencies() -> bool:
    header("Installing dependencies")
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        print("[WARNING] requirements.txt not found, skipping.")
        return True
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
        print("[OK] Dependencies installed.")
        return True
    except subprocess.CalledProcessError:
        print("[ERROR] Failed to install dependencies.")
        return False


def clean() -> None:
    header("Cleaning previous build artifacts")
    # Clean PyInstaller temp build folder (inside build dir, not build dir itself!)
    pyinst_build = BUILD_DIR / "POE2Sentinel"
    if pyinst_build.exists():
        print(f"Removing {pyinst_build}/ ...")
        shutil.rmtree(pyinst_build, ignore_errors=True)
    # Clean dist folder
    dist_path = PROJECT_ROOT / "dist"
    if dist_path.exists():
        print(f"Removing {dist_path}/ ...")
        shutil.rmtree(dist_path, ignore_errors=True)
    print("[OK] Clean complete.")


def build_exe() -> bool:
    header("Building executable")
    print("Running PyInstaller (this can take a few minutes)...")
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--clean", "--noconfirm"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] PyInstaller failed (code {exc.returncode}).")
        return False

    if EXE_PATH.exists():
        print(f"[OK] Executable created: {EXE_PATH}")
        return True
    print(f"[ERROR] Executable not found at {EXE_PATH}")
    return False


def find_iscc():
    """Locate the Inno Setup compiler (ISCC.exe)."""
    try:
        result = subprocess.run(["where", "ISCC.exe"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    for path in (
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.join(local_appdata, "Programs", "Inno Setup 6", "ISCC.exe"),
    ):
        if path and os.path.exists(path):
            return path
    return None


def build_installer() -> bool:
    header("Building installer")
    iscc = find_iscc()
    if not iscc:
        print("[WARNING] Inno Setup (ISCC.exe) not found - skipping installer.")
        print("Install from https://jrsoftware.org/isdl.php and re-run.")
        return False

    tess_path = PROJECT_ROOT / "tesseract-portable"
    if not tess_path.exists():
        print("[WARNING] tesseract-portable/ not found - OCR fallback won't work.")

    print(f"Using Inno Setup: {iscc}")
    try:
        subprocess.run([iscc, str(BUILD_DIR / "installer.iss")], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Installer build failed (code {exc.returncode}).")
        return False

    installers = list((PROJECT_ROOT / "dist").glob("POE2Sentinel_Setup_*.exe"))
    if installers:
        size = installers[0].stat().st_size / (1024 * 1024)
        print(f"[OK] Installer created: {installers[0].name} ({size:.1f} MB)")
        return True
    print("[WARNING] Installer file not found.")
    return False


def main() -> int:
    header("POE2 Sentinel - Build")
    if not install_dependencies():
        return 1
    if not ensure_pyinstaller():
        return 1
    clean()
    if not build_exe():
        return 1
    installer_ok = build_installer()

    header("Build complete")
    print(f"  Portable app: {DIST_APP}")
    if installer_ok:
        print("  Installer:    dist/POE2Sentinel_Setup_v*.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
