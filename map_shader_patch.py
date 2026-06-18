"""POE2 minimap shader patcher (reveal layout + keep fog of war).

Edits the game's on-disk asset bundles via the LibGGPK3 / LibBundle3 .NET
libraries (driven through pythonnet). The key change inserts a *visibility
floor* into ``shaders/minimap_visibility_pixel.hlsl``::

    res_color.r = max(res_color.r, <threshold>f);
    return res_color;

Unlike the memory reveal (which forces the explored flag and erases fog),
clamping the per-pixel visibility to a small floor makes unexplored tiles
faintly visible (you see the layout) while explored tiles stay brighter, so
fog of war is preserved.

The game MUST be closed before patching (it locks the bundle files), and the
edit is on-disk: it is wiped by game updates / file verification and must be
reapplied. Use Steam "Verify integrity of game files" to fully revert.
"""

import logging
import os
import shutil
import tempfile
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Shader assets inside the bundle and the patch anchors.
# In POE2's minimap_visibility_pixel.hlsl, res_color.r is the per-pixel
# visibility (0 unexplored .. 1 explored). We floor it just before the
# function returns so unexplored tiles stay faintly visible (layout + fog).
VISIBILITY_FILE = "shaders/minimap_visibility_pixel.hlsl"
RETURN_ANCHOR = "return res_color;"
FLOOR_MARKER = "res_color.r = max(res_color.r, "
DEFAULT_THRESHOLD = 0.18

# Win32 HResults for sharing/lock violations - locale-independent lock detection
# (0x80070020 ERROR_SHARING_VIOLATION, 0x80070021 ERROR_LOCK_VIOLATION).
_LOCK_HRESULTS = {-2147024864, -2147024863}

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libggpk")
_clr_ready = False
_clr_lock = threading.Lock()


class ShaderPatchError(Exception):
    """Base error for shader patching."""


class GameRunningError(ShaderPatchError):
    """Raised when bundle files are locked (POE2 is running)."""


class IndexNotFoundError(ShaderPatchError):
    """Raised when the POE2 bundle index cannot be located."""


class AnchorNotFoundError(ShaderPatchError):
    """Raised when the expected shader source anchor is missing."""


def _clamp_threshold(threshold: float) -> float:
    """Clamp the visibility floor to a finite value in [0.0, 1.0]."""
    try:
        value = float(threshold)
    except (TypeError, ValueError):
        raise ShaderPatchError(f"Invalid threshold: {threshold!r}")
    if value != value or value in (float("inf"), float("-inf")):  # NaN / +-inf
        raise ShaderPatchError(f"Invalid threshold: {threshold!r}")
    return min(1.0, max(0.0, value))


def _is_lock_error(exc) -> bool:
    """True if a .NET exception indicates a file sharing/lock violation."""
    if getattr(exc, "HResult", None) in _LOCK_HRESULTS:
        return True
    return "used by another process" in str(exc).lower()


def _atomic_copy(src: str, dst: str) -> None:
    """Copy ``src`` onto ``dst`` atomically (temp file in dst's dir, then replace)."""
    dst_dir = os.path.dirname(dst) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=dst_dir)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)  # atomic rename on the same volume
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _ensure_clr() -> None:
    """Load the .NET runtime and LibGGPK3 assemblies exactly once (thread-safe)."""
    global _clr_ready
    if _clr_ready:
        return
    with _clr_lock:
        if _clr_ready:
            return
        if not os.path.isdir(_LIB_DIR):
            raise ShaderPatchError(f"Missing libggpk folder: {_LIB_DIR}")
        os.add_dll_directory(_LIB_DIR)  # let .NET resolve native oo2core.dll
        from pythonnet import load
        load("coreclr")
        import clr  # noqa: F401
        for dll in ("SystemExtensions.dll", "LibBundle3.dll", "LibBundledGGPK3.dll"):
            clr.AddReference(os.path.join(_LIB_DIR, dll))
        _clr_ready = True
        logger.debug("LibGGPK3 .NET assemblies loaded")


# Path of the bundle index relative to a Steam library root.
_INDEX_RELATIVE = os.path.join(
    "steamapps", "common", "Path of Exile 2", "Bundles2", "_.index.bin"
)
# Fallback Steam install roots, probed only if the registry + libraryfolders.vdf
# lookup turns up nothing (e.g. registry key missing on a portable Steam).
_STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"C:\Steam",
    r"D:\Steam",
    r"E:\Steam",
    r"F:\Steam",
    r"G:\Steam",
    r"G:\Games\Steam",
    r"D:\Games\Steam",
    r"E:\Games\Steam",
]


def _steam_root_from_registry() -> Optional[str]:
    """Return the Steam install root from the Windows registry, if present.

    Reads ``HKCU\\Software\\Valve\\Steam\\SteamPath`` (the value Steam itself
    writes on install). Returns None on non-Windows or if the key is missing.
    """
    try:
        import winreg
    except ImportError:
        return None
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value_name = "SteamPath" if hive == winreg.HKEY_CURRENT_USER \
                    else "InstallPath"
                root, _ = winreg.QueryValueEx(handle, value_name)
                if root and os.path.isdir(root):
                    return os.path.normpath(root)
        except OSError:
            continue
    return None


def _steam_library_roots(steam_root: str) -> list:
    """Parse ``libraryfolders.vdf`` to list every Steam library folder.

    Steam records all library folders (on any drive) in this file, so parsing
    it covers custom library names like ``D:\\SteamLibrary``. Falls back to the
    Steam root itself if the file is missing or unparseable.
    """
    import re
    roots = [steam_root]
    for rel in (
        os.path.join("steamapps", "libraryfolders.vdf"),
        os.path.join("config", "libraryfolders.vdf"),
    ):
        vdf_path = os.path.join(steam_root, rel)
        if not os.path.isfile(vdf_path):
            continue
        try:
            with open(vdf_path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError as exc:
            logger.debug("Could not read %s: %s", vdf_path, exc)
            continue
        # Each library is a "path"  "<folder>" line; \\ is escaped in the VDF.
        for match in re.finditer(r'"path"\s*"([^"]+)"', text):
            path = match.group(1).replace("\\\\", "\\")
            if os.path.isdir(path) and path not in roots:
                roots.append(path)
    return roots


def find_poe2_index() -> Optional[str]:
    """Best-effort locate ``Bundles2/_.index.bin`` for POE2.

    Resolution order: the Steam root from the registry (expanded via
    ``libraryfolders.vdf`` to every library folder on any drive), then a list
    of common hardcoded roots as a last-resort fallback.
    """
    candidate_roots: list = []
    steam_root = _steam_root_from_registry()
    if steam_root:
        candidate_roots.extend(_steam_library_roots(steam_root))
    for root in _STEAM_ROOTS:
        if root not in candidate_roots:
            candidate_roots.append(root)

    for root in candidate_roots:
        candidate = os.path.join(root, _INDEX_RELATIVE)
        if os.path.isfile(candidate):
            return candidate
    return None


def _open_index(index_path: str, attempts: int = 8, delay: float = 0.4):
    """Open the bundle index, retrying transient locks.

    The 113 MB index is briefly locked by antivirus right after a restore
    copies it back, and is held for the whole session while POE2 runs. Retry a
    few times to ride out the transient AV lock; if it never releases, surface
    a friendly GameRunningError instead of a raw .NET IOException stack trace.
    """
    import time
    import LibBundle3
    last_err = None
    for attempt in range(attempts):
        try:
            index = LibBundle3.Index(index_path, False)  # default drive factory
            index.ParsePaths()
            return index
        except Exception as exc:  # noqa: BLE001 - .NET IOException, etc.
            last_err = exc
            if not _is_lock_error(exc):
                raise
            if attempt < attempts - 1:
                time.sleep(delay)
    raise GameRunningError(
        "The bundle index is locked (close Path of Exile 2, and wait a moment "
        "for antivirus to finish, then retry)."
    ) from last_err


def _find_record(index, rel_path: str):
    """Return the FileRecord for ``rel_path`` (e.g. ``shaders/foo.hlsl``)."""
    target = rel_path.lower()
    for rec in index.Files.Values:
        p = rec.Path
        if p and p.lower() == target:
            return rec
    return None


def _get_bundle(record) -> Tuple[object, Optional[str]]:
    """Open the bundle for ``record`` via the 2-out TryGetBundle overload.

    Returns ``(bundle, error_text)``; ``bundle`` is None on failure.
    """
    from System import Array, Object
    br = record.BundleRecord
    method = next(
        (m for m in br.GetType().GetMethods()
         if m.Name == "TryGetBundle" and len(m.GetParameters()) == 2),
        None,
    )
    if method is None:
        raise ShaderPatchError("LibBundle3 API changed: TryGetBundle(2-arg) not found")
    args = Array[Object]([None, None])
    ok = method.Invoke(br, args)
    if ok:
        return args[0], None
    exc = args[1]
    return None, (str(exc.Message) if exc is not None else "unknown error")


def _read_record_text(record) -> str:
    """Decode a shader FileRecord to ASCII text (raises on lock)."""
    bundle, err = _get_bundle(record)
    if bundle is None:
        if err and "used by another process" in err.lower():
            raise GameRunningError(
                "Bundle file is locked. Close Path of Exile 2 and retry."
            )
        raise ShaderPatchError(f"Could not open bundle: {err}")
    # TryGetBundle hands back an open file handle; dispose it or the .bundle.bin
    # stays locked for the life of the process (which blocks custom-bundle
    # cleanup and made POE2-launch diagnostics unreliable).
    try:
        data = bytes(record.Read(bundle).ToArray())
    finally:
        bundle.Dispose()
    # latin-1 is a lossless byte<->char mapping, so the text round-trips exactly
    # on write (the ASCII anchors/markers still match within it).
    return data.decode("latin-1")


def _build_visibility_patch(text: str, threshold: float) -> Optional[str]:
    """Return patched shader text, or None if already patched.

    Inserts ``res_color.r = max(res_color.r, <threshold>f);`` immediately
    before ``return res_color;``, matching the return line's indentation and
    the file's newline style.
    """
    if FLOOR_MARKER in text:
        return None
    pos = text.find(RETURN_ANCHOR)
    if pos == -1:
        raise AnchorNotFoundError(
            f"Anchor not found in {VISIBILITY_FILE}: {RETURN_ANCHOR!r}"
        )
    line_start = text.rfind("\n", 0, pos) + 1
    indent = text[line_start:pos]
    eol = text.find("\n", pos)
    nl = "\r\n" if eol > 0 and text[eol - 1] == "\r" else "\n"
    new_line = f"{indent}res_color.r = max(res_color.r, {threshold:g}f);{nl}"
    return text[:line_start] + new_line + text[line_start:]


def _resolve_index(index_path: Optional[str]) -> str:
    path = index_path or find_poe2_index()
    if not path or not os.path.isfile(path):
        raise IndexNotFoundError(
            "Could not find POE2 Bundles2/_.index.bin. Pass index_path."
        )
    return path


def read_shader(index_path: Optional[str] = None,
                rel_path: str = VISIBILITY_FILE) -> str:
    """Read and decode a shader asset from the bundle (read-only)."""
    _ensure_clr()
    path = _resolve_index(index_path)
    index = _open_index(path)
    try:
        rec = _find_record(index, rel_path)
        if rec is None:
            raise ShaderPatchError(f"Shader not found in bundle: {rel_path}")
        return _read_record_text(rec)
    finally:
        index.Dispose()


def get_status(index_path: Optional[str] = None) -> dict:
    """Return patch status: keys index_path, patched, threshold."""
    _ensure_clr()
    path = _resolve_index(index_path)
    text = read_shader(path, VISIBILITY_FILE)
    patched = FLOOR_MARKER in text
    threshold = _parse_threshold(text) if patched else None
    return {"index_path": path, "patched": patched, "threshold": threshold}


def _parse_threshold(text: str) -> Optional[float]:
    """Return the visibility floor currently present in ``text``, or None."""
    i = text.find(FLOOR_MARKER)
    if i == -1:
        return None
    start = i + len(FLOOR_MARKER)
    end = text.find(")", start)
    if end == -1:
        return None
    try:
        return float(text[start:end].strip().rstrip("f"))
    except ValueError:
        return None


def _custom_bundle_dir(index_path: str) -> str:
    """Path to LibBundle3's custom-bundle folder (where Replace writes)."""
    return os.path.join(os.path.dirname(index_path), "LibGGPK3")


def _count_custom_bundles(index_path: str) -> int:
    """Number of LibGGPK3/*.bundle.bin files currently on disk."""
    cdir = _custom_bundle_dir(index_path)
    if not os.path.isdir(cdir):
        return 0
    return sum(1 for n in os.listdir(cdir)
               if n.lower().endswith(".bundle.bin"))


def _is_custom_record(record) -> bool:
    """True if the shader is served from a LibGGPK3 custom bundle (patched)."""
    br = record.BundleRecord
    path = getattr(br, "Path", "") or ""
    return "libggpk3" in path.lower()


def _replace_record(index, new_text: str) -> None:
    """Write ``new_text`` into the visibility shader via the Replace-from-file API.

    pythonnet can't pass a byte[] to FileRecord.Write(ReadOnlySpan<byte>), so the
    new shader is written to a temp file and Index.Replace pulls it from disk.
    """
    import tempfile
    import LibBundle3
    fd, tmp = tempfile.mkstemp(suffix=".hlsl")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_text.encode("latin-1"))
        replaced = LibBundle3.Index.Replace(index, VISIBILITY_FILE, tmp, None, True)
    finally:
        os.unlink(tmp)
    if replaced < 1:
        raise ShaderPatchError("Replace reported 0 files written")


def snapshot_pristine(index_path: str) -> str:
    """Refresh the pristine ``.orig.bak`` snapshot from a vanilla index.

    Must only be called when the on-disk index is truly vanilla (shader
    unpatched and no custom bundle) so the snapshot stays valid for the
    current game version. The index must be closed before calling. The copy is
    atomic so an interrupted run cannot leave a truncated backup.
    """
    backup = index_path + ".orig.bak"
    _atomic_copy(index_path, backup)
    logger.info("Pristine index snapshot refreshed: %s", backup)
    return backup


def _remove_custom_bundles(cdir: str, attempts: int = 12,
                           delay: float = 0.5) -> bool:
    """Delete the LibGGPK3 custom-bundle folder, retrying transient locks.

    An orphaned custom bundle left in Bundles2 makes POE2 hang on launch even
    when the index no longer references it, so deletion must reliably succeed.
    Antivirus (or a lingering handle) can briefly lock a freshly written
    bundle; retry, deleting files individually so one stubborn file does not
    abort the whole cleanup.

    Returns True if the folder is gone (or never existed), False if a file
    could not be deleted within the retry window.
    """
    import stat
    import time
    for attempt in range(attempts):
        if not os.path.isdir(cdir):
            return True
        for name in os.listdir(cdir):
            fp = os.path.join(cdir, name)
            try:
                os.chmod(fp, stat.S_IWRITE)
            except OSError:
                pass
            try:
                os.remove(fp)
            except OSError:
                pass
        try:
            os.rmdir(cdir)
        except OSError:
            pass
        if not os.path.isdir(cdir):
            return True
        if attempt < attempts - 1:
            time.sleep(delay)
    logger.warning("Could not fully remove %s (custom bundle still locked)",
                   cdir)
    return not os.path.isdir(cdir)


def restore_pristine(index_path: str) -> bool:
    """Restore the vanilla index and delete LibGGPK3 custom bundles.

    Returns the index to a pristine, game-loadable state. The vanilla index is
    copied back first, then the custom bundle folder is deleted. The index must
    be closed before calling. Raises if no pristine snapshot exists.

    Returns True if the custom bundle folder was fully removed, False if an
    orphan bundle file is still locked on disk (the index is vanilla either
    way, but a lingering orphan will hang POE2 on launch).
    """
    backup = index_path + ".orig.bak"
    if not os.path.isfile(backup):
        raise ShaderPatchError(
            "No pristine backup (_.index.bin.orig.bak) to restore from. "
            "Use Steam 'Verify integrity of game files' to recover."
        )
    _atomic_copy(backup, index_path)
    removed = _remove_custom_bundles(_custom_bundle_dir(index_path))
    logger.info("Restored pristine index%s", "" if removed
                else " (WARNING: custom bundle deletion incomplete)")
    return removed


def apply_patch(index_path: Optional[str] = None,
                threshold: float = DEFAULT_THRESHOLD,
                backup: bool = True) -> dict:
    """Insert (or re-apply at a new threshold) the visibility floor.

    Always patches from a pristine index: if the shader is already patched at
    the same threshold (from a single clean custom bundle) this is a no-op;
    otherwise the index is first restored to vanilla, then a single Replace is
    performed. This guarantees exactly one custom bundle and avoids the bundle
    stacking that makes POE2 fail to launch with "deadlock detected".

    Returns a result dict with keys: status (patched/already_patched),
    threshold, index_path.
    """
    threshold = _clamp_threshold(threshold)
    _ensure_clr()
    path = _resolve_index(index_path)

    # Cheap state probe (open then close before any file-level restore).
    index = _open_index(path)
    try:
        rec = _find_record(index, VISIBILITY_FILE)
        if rec is None:
            raise ShaderPatchError(f"Shader not found: {VISIBILITY_FILE}")
        text = _read_record_text(rec)  # raises GameRunningError if locked
        patched = FLOOR_MARKER in text
        current = _parse_threshold(text) if patched else None
        from_custom = _is_custom_record(rec)
    finally:
        index.Dispose()

    # Already patched at the requested threshold from a single referenced
    # custom bundle -> nothing to do.
    if patched and from_custom and current is not None \
            and abs(current - threshold) < 1e-9 \
            and _count_custom_bundles(path) == 1:
        return {"status": "already_patched", "threshold": threshold,
                "index_path": path}

    # Make the index reference zero custom bundles before patching, so the
    # single Replace below leaves exactly one *referenced* custom bundle. This
    # is what avoids the bundle stacking that makes POE2 fail with "deadlock
    # detected". "Vanilla" is judged from the shader's bundle record (not stray
    # on-disk files): if the shader is unpatched and served from a real game
    # bundle, the live index is already pristine.
    if (not patched) and (not from_custom):
        if backup:
            snapshot_pristine(path)  # keep snapshot current to game version
        _remove_custom_bundles(_custom_bundle_dir(path))  # tidy stray orphans
    else:
        restore_pristine(path)       # roll back any prior / stacked patch

    # Patch the now-pristine shader with exactly one Replace.
    index = _open_index(path)
    try:
        rec = _find_record(index, VISIBILITY_FILE)
        text = _read_record_text(rec)
        new_text = _build_visibility_patch(text, threshold)
        if new_text is None:  # defensive: pristine should never be patched
            return {"status": "already_patched", "threshold": threshold,
                    "index_path": path}
        _replace_record(index, new_text)
        logger.info("Patched %s with floor %g", VISIBILITY_FILE, threshold)
        return {"status": "patched", "threshold": threshold, "index_path": path}
    finally:
        index.Dispose()


def remove_patch(index_path: Optional[str] = None) -> dict:
    """Strip the visibility floor, restoring vanilla fog-of-war rendering.

    Rather than editing the shader again (which would create yet another
    custom bundle), this restores the pristine index snapshot and deletes the
    LibGGPK3 custom bundles, returning a truly vanilla, game-loadable state.

    Returns a result dict with keys: status (removed/not_patched), index_path.
    """
    _ensure_clr()
    path = _resolve_index(index_path)

    index = _open_index(path)
    try:
        rec = _find_record(index, VISIBILITY_FILE)
        if rec is None:
            raise ShaderPatchError(f"Shader not found: {VISIBILITY_FILE}")
        text = _read_record_text(rec)  # raises GameRunningError if locked
        patched = FLOOR_MARKER in text
        from_custom = _is_custom_record(rec)
    finally:
        index.Dispose()

    if from_custom or patched:
        if not restore_pristine(path):
            raise ShaderPatchError(
                "Restored the vanilla index but could not delete the custom "
                "bundle in Bundles2\\LibGGPK3 (a file is locked). POE2 will "
                "hang on launch until it is gone. Close Path of Exile 2, let "
                "any antivirus scan finish, then click Remove again."
            )
        logger.info("Removed visibility floor (restored pristine index)")
        return {"status": "removed", "index_path": path}

    # Shader already vanilla; tidy up any orphaned custom bundles.
    if not _remove_custom_bundles(_custom_bundle_dir(path)):
        raise ShaderPatchError(
            "The index is already vanilla but a custom bundle remains in "
            "Bundles2\\LibGGPK3 (a file is locked). POE2 will hang on launch "
            "until it is gone. Close Path of Exile 2 and retry."
        )
    return {"status": "not_patched", "index_path": path}


def _main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="POE2 minimap shader patcher")
    parser.add_argument("command",
                        choices=["status", "inspect", "apply", "remove"],
                        help="status: show patch state; inspect: dump shader; "
                             "apply: insert visibility floor; "
                             "remove: strip the floor (restore fog)")
    parser.add_argument("--index", help="Path to Bundles2/_.index.bin")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="Visibility floor 0.0-1.0 (default 0.18)")
    args = parser.parse_args()
    try:
        if args.command == "status":
            print(get_status(args.index))
        elif args.command == "inspect":
            print(read_shader(args.index, VISIBILITY_FILE))
        elif args.command == "apply":
            print(apply_patch(args.index, args.threshold))
        elif args.command == "remove":
            print(remove_patch(args.index))
    except GameRunningError as e:
        print(f"ERROR: {e}")
        return 2
    except ShaderPatchError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
