"""
Flask Bot Module - POE2 auto flask bot with Memory and OCR support.
Uses pointer chains to read HP/Mana directly from game memory.
Falls back to OCR-based detection if memory reading fails.
Includes map reveal functionality via AOB pattern scanning.
"""

import keyboard
import time
import threading
import json
import os
import sys
import logging
import struct
import pymem
import pymem.process
import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import Optional, Callable, Dict, Any, List, Tuple

# OCR imports (optional - graceful fallback if not available)
try:
    import mss
    import pytesseract
    from PIL import Image, ImageOps
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Foreground-window detection (optional - graceful fallback if not available)
try:
    import win32gui
    import pygetwindow as gw
    WINDOW_API_AVAILABLE = True
except ImportError:
    WINDOW_API_AVAILABLE = False

logger = logging.getLogger(__name__)
_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS if OCR_AVAILABLE else None

# Windows API constants for memory operations
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PAGE_EXECUTE_READWRITE = 0x40

# Upper bound for a plausible HP/ES/Mana pool. Real PoE2 pools stay far below
# this; garbage reads from a stale pointer read as huge or negative and fail it.
VITAL_SANE_MAX = 200_000


def _init_kernel32(k) -> None:
    """Set argtypes/restypes so 64-bit handles/pointers are not truncated."""
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.ReadProcessMemory.restype = wintypes.BOOL
    k.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                     ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.WriteProcessMemory.restype = wintypes.BOOL
    k.VirtualProtectEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    k.VirtualProtectEx.restype = wintypes.BOOL


def _get_base_dir() -> str:
    """Return the directory for config files."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_get_base_dir(), "config.json")

DEFAULT_CONFIG = {
    "game_version": "steam",
    "detection_mode": "structure",  # "structure" (recommended), "memory", or "ocr"
    "life": {
        "threshold_mode": "percent",
        "threshold_percent": 70.0,
        "threshold_absolute": 500,
        "flask_key": "1",
        "confirmations_required": 2,
        "cooldown": 2.0,
        "pool_type": "hp",  # "hp", "es" (for ES builds), or "combined" (HP+ES)
        "region": {"top": 1089, "left": 151, "width": 119, "height": 27},  # OCR region
    },
    "mana": {
        "threshold_mode": "percent",
        "threshold_percent": 50.0,
        "threshold_absolute": 300,
        "flask_key": "2",
        "confirmations_required": 2,
        "cooldown": 2.0,
        "region": {"top": 1054, "left": 2397, "width": 83, "height": 34},  # OCR region
    },
    "poll_interval": 0.1,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` onto a deep copy of ``base``."""
    result = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """Load configuration merged over defaults; recover from a corrupt/missing file."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return _deep_merge(DEFAULT_CONFIG, {})
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("config root is not a JSON object")
        return _deep_merge(DEFAULT_CONFIG, loaded)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.error("Failed to read config (%s); falling back to defaults", e)
        return _deep_merge(DEFAULT_CONFIG, {})


def save_config(config: dict) -> None:
    """Save configuration atomically (write temp file, then replace)."""
    tmp_path = CONFIG_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    except OSError as e:
        logger.error("Failed to save config: %s", e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


class MemoryReader:
    """Reads HP/Mana from POE2 memory using pointer chains."""

    PROCESS_NAMES = {
        "steam": "PathOfExileSteam.exe",
        "standalone": "PathOfExile.exe",
        "epic": "PathOfExile.exe",
    }

    # Default pointer chains (Patch 0.5.1) - can be overridden via config
    DEFAULT_OFFSETS = {
        "current_hp_base": 0x042A01C8,
        "current_hp_chain": [0x0, 0x28, 0x70, 0x78, 0x504],
        "max_hp_base": 0x0443E9E8,
        "max_hp_chain": [0x30, 0x10, 0x0, 0x10, 0x0, 0x20, 0x2E8],
        "current_mp_base": 0x0443E9E8,
        "current_mp_chain": [0x38, 0x8, 0x10, 0x20, 0x504],
        "max_mp_base": 0x0443E9E8,
        "max_mp_chain": [0x38, 0x10, 0x20, 0x28, 0x3C8],
    }

    def __init__(self, game_version: str = "steam", config: Optional[dict] = None):
        self.game_version = game_version
        self.pm: Optional[pymem.Pymem] = None
        self.base_address: int = 0
        self.connected = False

        # Load offsets from config or use defaults
        self._load_offsets(config)

    def _load_offsets(self, config: Optional[dict]) -> None:
        """Load memory offsets from config or use defaults."""
        offsets = {}
        if config:
            offsets = config.get("memory_offsets", {})

        def parse_hex(value):
            """Parse hex string or return int as-is."""
            if isinstance(value, str):
                return int(value, 16)
            return value

        def parse_chain(chain):
            """Parse a chain of hex strings or ints."""
            if not chain:
                return []
            return [parse_hex(v) for v in chain]

        # Load each offset with fallback to defaults
        self.current_hp_base = parse_hex(offsets.get("current_hp_base", self.DEFAULT_OFFSETS["current_hp_base"]))
        self.current_hp_chain = parse_chain(offsets.get("current_hp_chain", self.DEFAULT_OFFSETS["current_hp_chain"]))
        self.max_hp_base = parse_hex(offsets.get("max_hp_base", self.DEFAULT_OFFSETS["max_hp_base"]))
        self.max_hp_chain = parse_chain(offsets.get("max_hp_chain", self.DEFAULT_OFFSETS["max_hp_chain"]))
        self.current_mp_base = parse_hex(offsets.get("current_mp_base", self.DEFAULT_OFFSETS["current_mp_base"]))
        self.current_mp_chain = parse_chain(offsets.get("current_mp_chain", self.DEFAULT_OFFSETS["current_mp_chain"]))
        self.max_mp_base = parse_hex(offsets.get("max_mp_base", self.DEFAULT_OFFSETS["max_mp_base"]))
        self.max_mp_chain = parse_chain(offsets.get("max_mp_chain", self.DEFAULT_OFFSETS["max_mp_chain"]))

        logger.debug(f"Loaded memory offsets - HP base: {hex(self.current_hp_base)}, MP base: {hex(self.current_mp_base)}")

    def reload_offsets(self, config: dict) -> None:
        """Reload memory offsets from updated config."""
        self._load_offsets(config)
        # Force reconnection to apply new offsets
        self.connected = False
        logger.info("Memory offsets reloaded, will reconnect on next read")

    def connect(self) -> bool:
        """Connect to the game process."""
        process_name = self.PROCESS_NAMES.get(self.game_version, "PathOfExileSteam.exe")
        try:
            self.pm = pymem.Pymem(process_name)
            self.base_address = self.pm.base_address
            self.connected = True
            logger.info(f"Connected to {process_name} at {hex(self.base_address)}")
            return True
        except Exception as e:
            logger.debug(f"Failed to connect: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the game process."""
        if self.pm:
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None
        self.connected = False

    def _read_pointer_chain(self, base: int, offsets: List[int]) -> Optional[int]:
        """Follow a chain of pointers to reach the final address.

        For each offset: read pointer at current address, then add offset.
        This matches how Cheat Engine pointer chains work.
        """
        if not self.pm:
            return None
        try:
            address = base
            for offset in offsets:
                # Read the pointer (64-bit) at current address
                ptr = self.pm.read_longlong(address)
                if ptr == 0:
                    return None
                # Add the offset to get next address
                address = ptr + offset
            return address
        except Exception:
            return None

    def _read_value(self, base_offset: int, chain: List[int]) -> int:
        """Read an integer value from a pointer chain."""
        try:
            base = self.base_address + base_offset
            addr = self._read_pointer_chain(base, chain)
            if addr:
                return self.pm.read_int(addr)
        except Exception:
            pass
        return 0

    def read_stats(self) -> Optional[Dict[str, int]]:
        """Read current HP and Mana stats."""
        if not self.connected:
            if not self.connect():
                return None

        try:
            hp_current = self._read_value(self.current_hp_base, self.current_hp_chain)
            hp_max = self._read_value(self.max_hp_base, self.max_hp_chain)
            mp_current = self._read_value(self.current_mp_base, self.current_mp_chain)
            mp_max = self._read_value(self.max_mp_base, self.max_mp_chain)

            # Sanity check
            if not (0 < hp_current <= VITAL_SANE_MAX and 0 < hp_max <= VITAL_SANE_MAX):
                self.connected = False
                return None

            return {
                "hp_current": hp_current,
                "hp_max": hp_max,
                "mp_current": mp_current,
                "mp_max": mp_max,
            }
        except Exception as e:
            logger.debug(f"Read failed: {e}")
            self.connected = False
            return None


class StructureReader:
    """Reads HP/Mana/ES from POE2 using structure-based memory reading.

    This approach uses AOB pattern scanning to find the GameState, then walks
    the game's internal structures to find the player entity and Life component.

    Benefits over pointer chains:
    - More stable across patches (only struct offsets may change, not full chains)
    - Works for all characters regardless of HP/ES configuration
    - Same approach used by POE2Radar and other tools

    The only offsets that may need updating per patch:
    - Life.HEALTH, Life.MANA, Life.ENERGY_SHIELD (component offsets)
    - VitalStruct.MAX, VitalStruct.CURRENT (struct layout)
    """

    PROCESS_NAMES = {
        "steam": "PathOfExileSteam.exe",
        "standalone": "PathOfExile.exe",
        "epic": "PathOfExile.exe",
    }

    # AOB pattern for finding GameStates
    GAME_STATES_PATTERN = [
        0x48, 0x83, 0xEC, None,           # sub rsp, ??
        0x48, 0x8B, 0xF1,                 # mov rsi, rcx
        0x33, 0xED,                       # xor ebp, ebp
        0x48, 0x39, 0x2D, None, None, None, None  # cmp [rip+rel32], rbp
    ]
    GAME_STATES_DISP_OFFSET = 12
    GAME_STATES_INSTR_LEN = 16

    # Structure offsets - these are the only things that may change per patch.
    # Last validated: 2026-06-04 against game build 4.5.2/311743
    # (single source: game_config.LAST_VALIDATED_BUILD; the GUI warns on drift).
    class Offsets:
        # GameState
        CURRENT_STATE_PTR = 0x08
        STATES = 0x48
        STATE_SLOT_STRIDE = 0x10
        STATE_SLOT_COUNT = 12

        # InGameState
        AREA_INSTANCE_DATA = 0x290

        # AreaInstance
        LOCAL_PLAYER = 0x5A0

        # Entity
        ENTITY_DETAILS_PTR = 0x08
        COMPONENT_LIST = 0x10

        # EntityDetails
        COMPONENT_LOOKUP_PTR = 0x28

        # ComponentLookUp
        NAME_AND_INDEX_BUCKET = 0x28
        ENTRY_STRIDE = 0x10

        # Life component - VitalStruct locations
        HEALTH = 0x1B0
        MANA = 0x208
        ENERGY_SHIELD = 0x248

        # VitalStruct layout
        VITAL_MAX = 0x2C
        VITAL_CURRENT = 0x30

    def __init__(self, game_version: str = "steam", config: Optional[dict] = None):
        self.game_version = game_version
        self.pm: Optional[pymem.Pymem] = None
        self.base_address: int = 0
        self.connected = False

        # Cached addresses
        self._game_state_slot: Optional[int] = None
        self._life_component_cache: Optional[int] = None
        self._cached_player_ptr: Optional[int] = None  # Track player ptr for zone change detection

        # Per-instance offset set (never mutate the shared class defaults).
        self._reset_offsets()
        self._load_offsets(config)

    def _reset_offsets(self) -> None:
        """Initialise this instance's offsets from the class defaults."""
        self.Offsets = SimpleNamespace(**{
            k: v for k, v in vars(StructureReader.Offsets).items()
            if not k.startswith("__")
        })

    def reload_offsets(self, config: dict) -> None:
        """Re-apply offsets from an updated config and force a reconnect."""
        self._reset_offsets()
        self._load_offsets(config)
        self.connected = False
        self._game_state_slot = None
        self._life_component_cache = None
        self._cached_player_ptr = None
        logger.info("Structure offsets reloaded, will reconnect on next read")

    def _load_offsets(self, config: Optional[dict]) -> None:
        """Load structure offsets from config (allows patching without code changes)."""
        if not config:
            return

        offsets = config.get("structure_offsets", {})
        if not offsets:
            return

        def parse_hex(value):
            if isinstance(value, str):
                return int(value, 16)
            return value

        # Override offsets if provided in config
        if "life_health" in offsets:
            self.Offsets.HEALTH = parse_hex(offsets["life_health"])
        if "life_mana" in offsets:
            self.Offsets.MANA = parse_hex(offsets["life_mana"])
        if "life_energy_shield" in offsets:
            self.Offsets.ENERGY_SHIELD = parse_hex(offsets["life_energy_shield"])
        if "vital_max" in offsets:
            self.Offsets.VITAL_MAX = parse_hex(offsets["vital_max"])
        if "vital_current" in offsets:
            self.Offsets.VITAL_CURRENT = parse_hex(offsets["vital_current"])
        if "area_instance_data" in offsets:
            self.Offsets.AREA_INSTANCE_DATA = parse_hex(offsets["area_instance_data"])
        if "local_player" in offsets:
            self.Offsets.LOCAL_PLAYER = parse_hex(offsets["local_player"])

        logger.debug(f"Structure offsets loaded - Life.HEALTH: 0x{self.Offsets.HEALTH:X}")

    def connect(self) -> bool:
        """Connect to the game process."""
        process_name = self.PROCESS_NAMES.get(self.game_version, "PathOfExileSteam.exe")
        try:
            self.pm = pymem.Pymem(process_name)
            self.base_address = self.pm.base_address
            self.connected = True
            self._game_state_slot = None  # Reset AOB cache on reconnect
            self._life_component_cache = None
            self._cached_player_ptr = None  # Reset player cache
            logger.info(f"StructureReader connected to {process_name} at 0x{self.base_address:X}")
            return True
        except Exception as e:
            logger.debug(f"StructureReader failed to connect: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the game process."""
        if self.pm:
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None
        self.connected = False
        self._game_state_slot = None
        self._life_component_cache = None

    def _read_ptr(self, address: int) -> Optional[int]:
        """Read a 64-bit pointer."""
        if not self.pm or address == 0:
            return None
        try:
            return self.pm.read_longlong(address)
        except Exception:
            return None

    def _read_int(self, address: int) -> Optional[int]:
        """Read a 32-bit integer."""
        if not self.pm or address == 0:
            return None
        try:
            return self.pm.read_int(address)
        except Exception:
            return None

    def _read_bytes(self, address: int, size: int) -> Optional[bytes]:
        """Read raw bytes from memory."""
        if not self.pm or address == 0 or size <= 0:
            return None
        try:
            return self.pm.read_bytes(address, size)
        except Exception:
            return None

    def _scan_for_pattern(self, pattern: List[Optional[int]], disp_offset: int,
                          instr_len: int) -> Optional[int]:
        """Scan for AOB pattern and resolve RIP-relative address."""
        if not self.pm:
            return None

        try:
            # Get module info
            module = pymem.process.module_from_name(self.pm.process_handle,
                                                     self.PROCESS_NAMES.get(self.game_version, "PathOfExileSteam.exe"))
            if not module:
                return None

            base = module.lpBaseOfDll
            size = module.SizeOfImage

            # Read in chunks to avoid memory issues
            chunk_size = 0x100000  # 1MB chunks
            pattern_len = len(pattern)

            for offset in range(0, size, chunk_size):
                read_size = min(chunk_size + pattern_len, size - offset)
                if read_size <= 0:
                    break

                chunk_base = base + offset
                try:
                    data = self.pm.read_bytes(chunk_base, read_size)
                except Exception:
                    continue

                # Search for pattern
                for i in range(len(data) - pattern_len + 1):
                    match = True
                    for j, pb in enumerate(pattern):
                        if pb is not None and data[i + j] != pb:
                            match = False
                            break

                    if match:
                        # Resolve RIP-relative address
                        disp_pos = i + disp_offset
                        if disp_pos + 4 > len(data):
                            continue

                        displacement = struct.unpack('<i', data[disp_pos:disp_pos + 4])[0]
                        resolved = chunk_base + i + instr_len + displacement

                        if resolved and resolved > 0x10000:
                            logger.debug(f"AOB match at 0x{chunk_base + i:X} -> 0x{resolved:X}")
                            return resolved

            return None
        except Exception as e:
            logger.error(f"AOB scan error: {e}")
            return None

    def _find_game_state_slot(self) -> Optional[int]:
        """Find GameState slot via AOB pattern scan (cached)."""
        if self._game_state_slot:
            return self._game_state_slot

        logger.info("Scanning for GameState AOB pattern...")
        slot = self._scan_for_pattern(
            self.GAME_STATES_PATTERN,
            self.GAME_STATES_DISP_OFFSET,
            self.GAME_STATES_INSTR_LEN
        )

        if slot:
            self._game_state_slot = slot
            logger.info(f"Found GameState slot at 0x{slot:X}")
        else:
            logger.warning("GameState AOB pattern not found")

        return slot

    def _find_local_player(self) -> Optional[int]:
        """Find the local player entity address.

        Chain: GameStateSlot -> GameState -> InGameState -> AreaInstance -> LocalPlayer
        """
        slot = self._find_game_state_slot()
        if not slot:
            return None

        # Dereference slot to get GameState
        game_state = self._read_ptr(slot)
        if not game_state or game_state < 0x10000:
            return None

        # Try to find valid InGameState
        candidates = []

        # Method 1: CurrentStatePtr StdVector
        vec_first = self._read_ptr(game_state + self.Offsets.CURRENT_STATE_PTR)
        if vec_first and vec_first > 0x10000:
            igs_ptr = self._read_ptr(vec_first)
            if igs_ptr and igs_ptr > 0x10000:
                candidates.append(igs_ptr)

        # Method 2: States array fallback
        for i in range(self.Offsets.STATE_SLOT_COUNT):
            slot_addr = game_state + self.Offsets.STATES + (i * self.Offsets.STATE_SLOT_STRIDE)
            igs_ptr = self._read_ptr(slot_addr)
            if igs_ptr and igs_ptr > 0x10000 and igs_ptr not in candidates:
                candidates.append(igs_ptr)

        # Validate candidates and find LocalPlayer
        for igs in candidates:
            area_instance = self._read_ptr(igs + self.Offsets.AREA_INSTANCE_DATA)
            if not area_instance or area_instance < 0x10000:
                continue

            local_player = self._read_ptr(area_instance + self.Offsets.LOCAL_PLAYER)
            if local_player and local_player > 0x10000:
                return local_player

        return None

    def _read_utf8_string(self, addr: int, max_length: int = 32) -> str:
        """Read a null-terminated UTF-8 string."""
        if not addr:
            return ""
        data = self._read_bytes(addr, max_length)
        if not data:
            return ""
        try:
            return data.split(b'\x00')[0].decode('utf-8')
        except Exception:
            return ""

    def _resolve_life_component(self, entity_ptr: int) -> Optional[int]:
        """Resolve the Life component address for an entity."""
        details = self._read_ptr(entity_ptr + self.Offsets.ENTITY_DETAILS_PTR)
        if not details:
            return None

        lookup = self._read_ptr(details + self.Offsets.COMPONENT_LOOKUP_PTR)
        if not lookup:
            return None

        # Read component list
        comp_list_begin = self._read_ptr(entity_ptr + self.Offsets.COMPONENT_LIST)
        comp_list_end = self._read_ptr(entity_ptr + self.Offsets.COMPONENT_LIST + 8)
        if not comp_list_begin or not comp_list_end or comp_list_end <= comp_list_begin:
            return None

        comp_count = (comp_list_end - comp_list_begin) // 8
        if comp_count <= 0 or comp_count > 256:
            return None

        # Read bucket
        bucket_begin = self._read_ptr(lookup + self.Offsets.NAME_AND_INDEX_BUCKET)
        bucket_end = self._read_ptr(lookup + self.Offsets.NAME_AND_INDEX_BUCKET + 8)
        if not bucket_begin or not bucket_end or bucket_end <= bucket_begin:
            return None

        num_entries = (bucket_end - bucket_begin) // self.Offsets.ENTRY_STRIDE
        if num_entries <= 0 or num_entries > 256:
            return None

        # Search for "Life" component
        for i in range(num_entries):
            entry_addr = bucket_begin + i * self.Offsets.ENTRY_STRIDE
            name_ptr = self._read_ptr(entry_addr)
            if not name_ptr:
                continue

            name = self._read_utf8_string(name_ptr)
            if name == "Life":
                index = self._read_int(entry_addr + 8)
                if index is not None and 0 <= index < comp_count:
                    return self._read_ptr(comp_list_begin + index * 8)

        return None

    @staticmethod
    def _sanitise_pool(cur: int, mx: int) -> Tuple[int, int]:
        """Clamp an optional (current, max) pool; return (0, 0) if implausible."""
        if not (0 < mx <= VITAL_SANE_MAX) or not (0 <= cur <= mx):
            return (0, 0)
        return (cur, mx)

    def _read_vital_struct(self, life_component: int, vital_offset: int) -> Tuple[int, int]:
        """Read current and max values from a VitalStruct."""
        need = max(self.Offsets.VITAL_MAX, self.Offsets.VITAL_CURRENT) + 4
        data = self._read_bytes(life_component + vital_offset, need)
        if not data or len(data) < need:
            return (0, 0)

        max_val = struct.unpack_from('<i', data, self.Offsets.VITAL_MAX)[0]
        cur_val = struct.unpack_from('<i', data, self.Offsets.VITAL_CURRENT)[0]

        return (cur_val, max_val)

    def read_stats(self) -> Optional[Dict[str, int]]:
        """Read current HP, ES, and Mana stats using structure-based approach."""
        if not self.connected:
            if not self.connect():
                return None

        try:
            # Find local player
            player = self._find_local_player()
            if not player:
                logger.debug("Could not find local player")
                return None

            # Zone change detection: if player pointer changed, invalidate Life cache
            if self._cached_player_ptr and self._cached_player_ptr != player:
                logger.debug(f"Zone change detected (player ptr: 0x{self._cached_player_ptr:X} -> 0x{player:X})")
                self._life_component_cache = None
            self._cached_player_ptr = player

            # Resolve Life component (with caching)
            if self._life_component_cache:
                life = self._life_component_cache
                # Validate cache is still valid
                test = self._read_bytes(life, 4)
                if not test:
                    life = self._resolve_life_component(player)
                    self._life_component_cache = life
            else:
                life = self._resolve_life_component(player)
                self._life_component_cache = life

            if not life:
                logger.debug("Could not resolve Life component")
                return None

            # Read HP, ES, and Mana
            hp_cur, hp_max = self._read_vital_struct(life, self.Offsets.HEALTH)
            es_cur, es_max = self._read_vital_struct(life, self.Offsets.ENERGY_SHIELD)
            mp_cur, mp_max = self._read_vital_struct(life, self.Offsets.MANA)

            # HP is always present in PoE2; an invalid HP read means a stale
            # pointer, so drop the cache and skip this tick.
            if not (0 < hp_max <= VITAL_SANE_MAX) or not (0 <= hp_cur <= hp_max):
                self._life_component_cache = None  # Invalidate cache
                self._cached_player_ptr = None  # Also reset player cache
                return None

            # ES/Mana are optional pools: sanitise each independently so a garbage
            # read for one cannot drive a flask decision.
            es_cur, es_max = self._sanitise_pool(es_cur, es_max)
            mp_cur, mp_max = self._sanitise_pool(mp_cur, mp_max)

            return {
                "hp_current": hp_cur,
                "hp_max": hp_max,
                "es_current": es_cur,
                "es_max": es_max,
                "mp_current": mp_cur,
                "mp_max": mp_max,
            }
        except Exception as e:
            logger.debug(f"StructureReader read failed: {e}")
            self._life_component_cache = None
            self._cached_player_ptr = None
            return None


def _configure_tesseract() -> None:
    """Point pytesseract at a usable Tesseract engine."""
    if not OCR_AVAILABLE:
        return

    candidates = [
        os.path.join(_get_base_dir(), "tesseract-portable", "tesseract.exe"),
        os.path.join(_get_base_dir(), "tesseract", "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    for path in candidates:
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            tessdata = os.path.join(os.path.dirname(path), "tessdata")
            if os.path.isdir(tessdata):
                os.environ.setdefault("TESSDATA_PREFIX", tessdata)
            logger.info(f"Using Tesseract at {path}")
            return

    logger.warning("Tesseract not found; OCR mode may not work")


# Configure tesseract on module load
_configure_tesseract()


class OCRReader:
    """Reads HP/Mana from POE2 using OCR (screen capture + Tesseract).

    This is a fallback method when memory reading doesn't work (e.g., after patches).
    Requires screen regions to be configured for life and mana display.
    """

    def __init__(self, config: dict):
        self.config = config
        self.learned_life_max = 0
        self.learned_mana_max = 0

    def read_stats(self) -> Optional[Dict[str, int]]:
        """Read current HP and Mana stats via OCR."""
        if not OCR_AVAILABLE:
            logger.error("OCR not available - install pytesseract, mss, pillow")
            return None

        life_cfg = self.config.get("life", {})
        mana_cfg = self.config.get("mana", {})

        life_region = life_cfg.get("region")
        mana_region = mana_cfg.get("region")

        if not life_region or not mana_region:
            logger.error("OCR regions not configured")
            return None

        # Read life
        life_reading = self._read_resource(life_region)
        if life_reading is None:
            return None

        life_current, life_max = life_reading
        if life_max:
            self.learned_life_max = life_max
        elif self.learned_life_max:
            life_max = self.learned_life_max
        else:
            # No max seen yet: percent thresholds need a real max, so skip this
            # cycle rather than faking max == current (which can never trigger).
            logger.debug("OCR life max not yet calibrated (need an 'x/y' reading)")
            return None

        # Read mana
        mana_reading = self._read_resource(mana_region)
        if mana_reading is None:
            return None

        mana_current, mana_max = mana_reading
        if mana_max:
            self.learned_mana_max = mana_max
        elif self.learned_mana_max:
            mana_max = self.learned_mana_max
        else:
            logger.debug("OCR mana max not yet calibrated (need an 'x/y' reading)")
            return None

        return {
            "hp_current": life_current,
            "hp_max": life_max,
            "mp_current": mana_current,
            "mp_max": mana_max,
        }

    def _read_resource(self, region: dict) -> Optional[Tuple[int, Optional[int]]]:
        """Capture a resource region and OCR it into (current, max)."""
        try:
            with mss.mss() as sct:
                shot = sct.grab(region)

            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").convert("L")
            img = ImageOps.autocontrast(img)
            img = img.resize((img.width * 3, img.height * 3), _RESAMPLE)

            text = pytesseract.image_to_string(
                img, config="--psm 7 -c tessedit_char_whitelist=0123456789/"
            )
        except Exception as e:
            logger.debug(f"OCR capture failed: {e}")
            return None

        return self._parse_reading(text)

    @staticmethod
    def _parse_reading(text: str) -> Optional[Tuple[int, Optional[int]]]:
        """Parse OCR text into (current, max)."""
        cleaned = text.strip().replace(" ", "")
        if not cleaned:
            return None

        if "/" in cleaned:
            parts = cleaned.split("/")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                return None
            current, maximum = int(parts[0]), int(parts[1])
            if maximum <= 0 or not 0 <= current <= maximum:
                return None
            return current, maximum

        if not cleaned.isdigit():
            return None
        return int(cleaned), None

    def disconnect(self) -> None:
        """No-op for OCR reader (no connection to close)."""
        pass


class AtlasFogReveal:
    """POE2 Atlas Fog Reveal using AOB pattern scanning.

    Removes the fog/unexplored areas on the Atlas map by NOPing the fog calculation.
    Pattern: f3 0f 59 51 ? f3 0f 58 c1 (mulss xmm2,[rcx+08] / addss xmm0,xmm1)
    """

    PROCESS_NAMES = {
        "steam": "PathOfExileSteam.exe",
        "standalone": "PathOfExile.exe",
        "epic": "PathOfExile.exe",
    }

    # AOB pattern for atlas fog - the ? is a wildcard (usually 08)
    # f3 0f 59 51 XX f3 0f 58 c1 - where XX is the wildcard byte
    # We search for partial pattern and verify the rest
    SEARCH_PATTERN_START = bytes([0xF3, 0x0F, 0x59, 0x51])  # mulss xmm2, [rcx+?]
    SEARCH_PATTERN_END = bytes([0xF3, 0x0F, 0x58, 0xC1])    # addss xmm0, xmm1

    # Original bytes to restore: f3 0f 59 51 08 f3 0f 58 c1
    ORIGINAL_BYTES = bytes([0xF3, 0x0F, 0x59, 0x51, 0x08, 0xF3, 0x0F, 0x58, 0xC1])

    # NOP replacement for first 5 bytes
    NOP_BYTES = bytes([0x90, 0x90, 0x90, 0x90, 0x90])
    BYTES_TO_PATCH = 5

    def __init__(self, game_version: str = "steam"):
        self.game_version = game_version
        self.pattern_address: Optional[int] = None
        self.is_enabled = False
        self.original_bytes: Optional[bytes] = None  # Store original for restore
        self._lock = threading.Lock()

        # Load kernel32 with correct 64-bit prototypes.
        self.kernel32 = ctypes.windll.kernel32
        _init_kernel32(self.kernel32)

    def _open_process(self, pid: int) -> Optional[int]:
        """Open process with read/write access."""
        handle = self.kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            False,
            pid
        )
        return handle if handle else None

    def _close_handle(self, handle: int) -> None:
        """Close process handle."""
        if handle:
            self.kernel32.CloseHandle(handle)

    def _read_memory(self, handle: int, address: int, size: int) -> Optional[bytes]:
        """Read exactly ``size`` bytes; return None on a short or failed read."""
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        success = self.kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        if not success or bytes_read.value != size:
            return None
        return buffer.raw[:bytes_read.value]

    def _write_memory(self, handle: int, address: int, data: bytes) -> bool:
        """Write ``data`` to executable memory, verifying the full write.

        The target is code in .text, so make the page writable for the write and
        restore its original protection afterwards.
        """
        size = len(data)
        old_protect = wintypes.DWORD(0)
        if not self.kernel32.VirtualProtectEx(
            handle, ctypes.c_void_p(address), size,
            PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)
        ):
            return False
        try:
            buffer = ctypes.create_string_buffer(data)
            bytes_written = ctypes.c_size_t()
            success = self.kernel32.WriteProcessMemory(
                handle, ctypes.c_void_p(address), buffer, size,
                ctypes.byref(bytes_written)
            )
            return bool(success) and bytes_written.value == size
        finally:
            restored = wintypes.DWORD(0)
            self.kernel32.VirtualProtectEx(
                handle, ctypes.c_void_p(address), size,
                old_protect.value, ctypes.byref(restored)
            )

    def _matches_original(self, current: bytes) -> bool:
        """True if ``current`` matches the fog instruction (index 4 is a wildcard)."""
        expected = self.ORIGINAL_BYTES[:self.BYTES_TO_PATCH]
        return all(current[i] == b for i, b in enumerate(expected) if i != 4)

    def _find_pattern(self, handle: int, pm: pymem.Pymem) -> Optional[int]:
        """Search for the Atlas fog AOB pattern in process memory.

        Pattern: f3 0f 59 51 ? f3 0f 58 c1 (with wildcard at position 4)
        """
        BUFFER_SIZE = 8192  # Larger buffer for efficiency

        # Enumerate loaded modules; never fall back to a blind, unbounded scan.
        try:
            modules = list(pm.list_modules())
        except Exception:
            return None
        if not modules:
            return None
        modules = [(m.lpBaseOfDll, m.SizeOfImage) for m in modules]

        for base_address, module_size in modules:
            try:
                for offset in range(0, module_size, BUFFER_SIZE - 16):
                    bytes_to_read = min(BUFFER_SIZE, module_size - offset)
                    data = self._read_memory(handle, base_address + offset, bytes_to_read)

                    if data:
                        # Search for pattern with wildcard
                        # Look for: f3 0f 59 51 [?] f3 0f 58 c1
                        search_pos = 0
                        while True:
                            idx = data.find(self.SEARCH_PATTERN_START, search_pos)
                            if idx == -1 or idx + 9 > len(data):
                                break

                            # Check if the pattern_end follows at offset +5
                            if data[idx + 5:idx + 9] == self.SEARCH_PATTERN_END:
                                found_addr = base_address + offset + idx
                                logger.info(f"Atlas fog pattern found at {hex(found_addr)}")
                                return found_addr

                            search_pos = idx + 1

            except Exception as e:
                continue

        return None

    def _get_process(self) -> Optional[pymem.Pymem]:
        """Get the game process."""
        process_name = self.PROCESS_NAMES.get(self.game_version, "PathOfExileSteam.exe")
        try:
            return pymem.Pymem(process_name)
        except Exception:
            return None

    def toggle(self) -> Tuple[bool, str]:
        """Toggle atlas fog reveal on/off. Returns (success, message)."""
        with self._lock:
            process = self._get_process()
            if not process:
                return False, "Game not running"

            handle = None
            try:
                handle = self._open_process(process.process_id)
                if not handle:
                    return False, "Failed to open process"

                # Find pattern if we haven't already
                if self.pattern_address is None:
                    self.pattern_address = self._find_pattern(handle, process)
                    if self.pattern_address is None:
                        return False, "Atlas fog pattern not found"

                current = self._read_memory(handle, self.pattern_address, self.BYTES_TO_PATCH)
                if current is None:
                    return False, "Failed to read memory"

                if current == self.NOP_BYTES:
                    # Currently enabled (NOPed) - restore the saved original bytes.
                    restore_bytes = self.original_bytes or self.ORIGINAL_BYTES[:self.BYTES_TO_PATCH]
                    if not self._write_memory(handle, self.pattern_address, restore_bytes):
                        return False, "Failed to write memory"
                    self.is_enabled = False
                    logger.info("Atlas fog reveal disabled (restored original)")
                    return True, "Atlas fog reveal disabled"

                # Currently disabled - verify this really is the fog instruction
                # before overwriting executable code, then NOP it.
                if not self._matches_original(current):
                    return False, "Unexpected bytes at pattern site (game updated?)"
                self.original_bytes = current  # Save for restore
                if not self._write_memory(handle, self.pattern_address, self.NOP_BYTES):
                    return False, "Failed to write memory"
                self.is_enabled = True
                logger.info("Atlas fog reveal enabled (NOPed)")
                return True, "Atlas fog reveal enabled"

            except Exception as e:
                logger.error(f"Atlas fog toggle error: {e}")
                return False, str(e)
            finally:
                if handle:
                    self._close_handle(handle)
                try:
                    process.close_process()
                except Exception:
                    pass

    def enable(self) -> Tuple[bool, str]:
        """Enable atlas fog reveal."""
        if self.is_enabled:
            return True, "Already enabled"
        return self.toggle()

    def disable(self) -> Tuple[bool, str]:
        """Disable atlas fog reveal."""
        if not self.is_enabled:
            return True, "Already disabled"
        return self.toggle()

    def get_status(self) -> bool:
        """Get current atlas fog reveal status."""
        return self.is_enabled

    def reset(self) -> None:
        """Reset cached pattern address (use after game restart)."""
        self.pattern_address = None
        self.original_bytes = None
        self.is_enabled = False


class FlaskBot:
    """POE2 Auto Flask Bot with Memory and OCR support."""

    def __init__(self, on_update: Optional[Callable[[str, int, int], None]] = None):
        self.config = load_config()
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.on_update = on_update
        self.detection_mode = self.config.get("detection_mode", "structure")
        self._init_reader()

        # Track last use times for cooldowns
        self.last_life_use = 0.0
        self.last_mana_use = 0.0
        self.life_low_streak = 0
        self.mana_low_streak = 0

    def _init_reader(self) -> None:
        """Initialize the appropriate reader based on detection mode."""
        # Sync detection mode from config
        self.detection_mode = self.config.get("detection_mode", "structure")

        if self.detection_mode == "ocr":
            self.reader = OCRReader(self.config)
            logger.info("Using OCR detection mode")
        elif self.detection_mode == "structure":
            self.reader = StructureReader(self.config.get("game_version", "steam"), self.config)
            logger.info("Using Structure-based detection mode (auto-updates across patches)")
        else:
            self.reader = MemoryReader(self.config.get("game_version", "steam"), self.config)
            logger.info("Using Memory detection mode (pointer chains)")

    def reload_config(self) -> None:
        """Reload configuration from file and re-apply it to the active reader."""
        self.config = load_config()
        reader = getattr(self, "reader", None)
        if isinstance(reader, OCRReader):
            reader.config = self.config
        elif reader is not None and hasattr(reader, "reload_offsets"):
            reader.reload_offsets(self.config)

    def set_detection_mode(self, mode: str) -> None:
        """Change detection mode (memory/ocr/structure)."""
        if mode not in ("memory", "ocr", "structure"):
            raise ValueError("Mode must be 'memory', 'ocr', or 'structure'")
        self.detection_mode = mode
        self.config["detection_mode"] = mode
        save_config(self.config)
        self._init_reader()

    def _get_threshold(self, resource: str, current_max: int) -> float:
        """Calculate the effective threshold for a resource."""
        cfg = self.config.get(resource, {})
        mode = cfg.get("threshold_mode", "percent")

        if mode == "percent":
            percent = cfg.get("threshold_percent", 50.0)
            return (percent / 100.0) * current_max
        else:
            return float(cfg.get("threshold_absolute", 500))

    def _is_poe_active(self) -> bool:
        """Check whether a Path of Exile window is currently in the foreground."""
        if not WINDOW_API_AVAILABLE:
            return False  # Cannot confirm focus -> never send keystrokes blindly.
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return False
            return "Path of Exile" in gw.Window(hwnd).title
        except Exception:
            return False

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        poll_interval = self.config.get("poll_interval", 0.1)

        while self.running:
            stats = self.reader.read_stats()

            if stats is None:
                time.sleep(1.0)  # Wait longer if not connected
                continue

            hp_current = stats["hp_current"]
            hp_max = stats["hp_max"]
            mp_current = stats["mp_current"]
            mp_max = stats["mp_max"]

            # Handle ES for structure reader (ES builds use ES as effective HP)
            es_current = stats.get("es_current", 0)
            es_max = stats.get("es_max", 0)

            # Determine effective life pool based on config
            life_cfg = self.config.get("life", {})
            life_pool = life_cfg.get("pool_type", "hp")  # "hp", "es", or "combined"

            if life_pool == "es" and es_max > 0:
                # Pure ES build - use ES as life pool
                effective_hp_current = es_current
                effective_hp_max = es_max
            elif life_pool == "combined" and es_max > 0:
                # Hybrid build - combine HP + ES
                effective_hp_current = hp_current + es_current
                effective_hp_max = hp_max + es_max
            else:
                # Default: HP only
                effective_hp_current = hp_current
                effective_hp_max = hp_max

            # Update UI (always, even when tabbed out)
            if self.on_update:
                self.on_update("life", effective_hp_current, effective_hp_max)
                self.on_update("mana", mp_current, mp_max)
                # Also report ES separately if available
                if es_max > 0:
                    self.on_update("es", es_current, es_max)

            # Only press keys if POE2 is the active window!
            if not self._is_poe_active():
                # Reset streaks when tabbed out to avoid instant flask on tab back
                self.life_low_streak = 0
                self.mana_low_streak = 0
                time.sleep(0.5)
                continue

            now = time.time()

            # Check Life (uses effective HP which may include ES based on pool_type)
            life_threshold = self._get_threshold("life", effective_hp_max)
            life_cooldown = life_cfg.get("cooldown", 2.0)
            life_confirms = life_cfg.get("confirmations_required", 2)

            if effective_hp_current <= life_threshold:
                self.life_low_streak += 1
            else:
                self.life_low_streak = 0

            if self.life_low_streak >= life_confirms and now - self.last_life_use >= life_cooldown:
                flask_key = life_cfg.get("flask_key", "1")
                keyboard.press_and_release(flask_key)
                logger.info(f"Life flask used at {effective_hp_current}/{effective_hp_max}")
                self.last_life_use = now
                self.life_low_streak = 0

            # Check Mana
            mana_cfg = self.config.get("mana", {})
            mana_threshold = self._get_threshold("mana", mp_max)
            mana_cooldown = mana_cfg.get("cooldown", 2.0)
            mana_confirms = mana_cfg.get("confirmations_required", 2)

            if mp_current <= mana_threshold:
                self.mana_low_streak += 1
            else:
                self.mana_low_streak = 0

            if self.mana_low_streak >= mana_confirms and now - self.last_mana_use >= mana_cooldown:
                flask_key = mana_cfg.get("flask_key", "2")
                keyboard.press_and_release(flask_key)
                logger.info(f"Mana flask used at {mp_current}/{mp_max}")
                self.last_mana_use = now
                self.mana_low_streak = 0

            time.sleep(poll_interval)

    def start(self) -> None:
        """Start the flask bot."""
        if self.running:
            return

        self.reload_config()
        self._init_reader()  # Use the correct reader based on detection_mode
        self.running = True
        self.life_low_streak = 0
        self.mana_low_streak = 0

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop(self) -> None:
        """Stop the flask bot and wait for the monitor thread to finish."""
        self.running = False
        thread = self.monitor_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.monitor_thread = None
        self.reader.disconnect()

    def is_running(self) -> bool:
        """Check if the bot is running."""
        return self.running
