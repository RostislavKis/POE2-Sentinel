"""
Custom styled dialogs for POE2 Flask Bot GUI.
Modern, themed dialogs that match the application design.
"""

import customtkinter as ctk
from typing import Literal, Optional


class CustomDialog:
    """Custom styled dialog that matches the application theme."""
    
    def __init__(
        self,
        parent,
        title: str,
        message: str,
        dialog_type: Literal["info", "warning", "error", "question"] = "info",
        buttons: Literal["ok", "ok_cancel", "yes_no"] = "ok",
        colors: Optional[dict] = None
    ):
        self.parent = parent
        self.title = title
        self.message = message
        self.dialog_type = dialog_type
        self.buttons = buttons
        self.result = None
        
        # Default colors (dark purple theme). Merge any provided colors on top
        # so callers that omit some keys (e.g. "info") don't trigger KeyError.
        default_colors = {
            "primary": "#6C5CE7",
            "primary_hover": "#5B4CD6",
            "bg_dark": "#1a1a2e",
            "bg_card": "#2b3447",
            "text": "#ffffff",
            "text_secondary": "#b8b8d1",
            "success": "#00D9A3",
            "warning": "#FFA500",
            "danger": "#FF4757",
            "info": "#6C5CE7"
        }
        self.colors = {**default_colors, **(colors or {})}
        
        # Icon and color based on dialog type
        self.type_config = {
            "info": {"icon": "ℹ️", "color": self.colors["info"]},
            "warning": {"icon": "⚠️", "color": self.colors["warning"]},
            "error": {"icon": "❌", "color": self.colors["danger"]},
            "question": {"icon": "❓", "color": self.colors["primary"]}
        }
        
        self.dialog = None
        
    def show(self) -> Optional[bool]:
        """Show the dialog and return the result."""
        self.dialog = ctk.CTkToplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.configure(fg_color=self.colors["bg_dark"])
        
        self._create_content()
        
        self.dialog.update_idletasks()
        
        # Size and position
        width, height = 450, 220
        if self.parent:
            x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - (width // 2)
            y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - (height // 2)
        else:
            x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
            y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        self.dialog.wait_window()
        
        return self.result
    
    def _create_content(self):
        """Create dialog content."""
        config = self.type_config[self.dialog_type]
        
        main_frame = ctk.CTkFrame(self.dialog, fg_color=self.colors["bg_card"], corner_radius=15)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Header with icon
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        icon_label = ctk.CTkLabel(header_frame, text=config["icon"], font=("Segoe UI", 28), text_color=config["color"])
        icon_label.pack(side="left", padx=(0, 12))
        
        title_label = ctk.CTkLabel(header_frame, text=self.title, font=("Segoe UI", 16, "bold"), text_color=self.colors["text"])
        title_label.pack(side="left")
        
        # Message
        msg_label = ctk.CTkLabel(
            main_frame, text=self.message, font=("Segoe UI", 12),
            text_color=self.colors["text_secondary"], wraplength=400, justify="left"
        )
        msg_label.pack(fill="x", padx=20, pady=10)
        
        # Buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(10, 20), side="bottom")
        
        if self.buttons == "ok":
            ctk.CTkButton(btn_frame, text="OK", command=self._on_ok, fg_color=self.colors["primary"],
                          hover_color=self.colors["primary_hover"], width=100, height=36).pack(side="right")
            self.dialog.bind("<Return>", lambda e: self._on_ok())
        elif self.buttons == "yes_no":
            ctk.CTkButton(btn_frame, text="No", command=self._on_no, fg_color=self.colors["bg_dark"],
                          hover_color="#3d4555", width=100, height=36).pack(side="right", padx=(10, 0))
            ctk.CTkButton(btn_frame, text="Yes", command=self._on_yes, fg_color=self.colors["success"],
                          hover_color="#00B386", width=100, height=36).pack(side="right")
            self.dialog.bind("<Return>", lambda e: self._on_yes())
            self.dialog.bind("<Escape>", lambda e: self._on_no())
    
    def _on_ok(self):
        self.result = True
        self.dialog.destroy()
    
    def _on_yes(self):
        self.result = True
        self.dialog.destroy()
    
    def _on_no(self):
        self.result = False
        self.dialog.destroy()


class MemoryOffsetsDialog:
    """Dialog for editing memory pointer offsets."""

    def __init__(self, parent, config: dict, colors: Optional[dict] = None):
        self.parent = parent
        self.config = config
        self.result = None

        # Default colors
        default_colors = {
            "primary": "#58A6FF",
            "bg_dark": "#0D1117",
            "bg_card": "#161B22",
            "bg_hover": "#21262D",
            "border": "#30363D",
            "text": "#E6EDF3",
            "text_secondary": "#7D8590",
            "success": "#3FB950",
            "danger": "#F85149",
        }
        self.colors = {**default_colors, **(colors or {})}
        self.dialog = None
        self.entries = {}

    def show(self) -> Optional[dict]:
        """Show the dialog and return the updated offsets or None if cancelled."""
        self.dialog = ctk.CTkToplevel(self.parent)
        self.dialog.title("Edit Memory Offsets")
        self.dialog.configure(fg_color=self.colors["bg_dark"])

        self._create_content()

        self.dialog.update_idletasks()

        # Size and position
        width, height = 550, 520
        if self.parent:
            x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - (width // 2)
            y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - (height // 2)
        else:
            x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
            y = (self.dialog.winfo_screenheight() // 2) - (height // 2)

        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        self.dialog.wait_window()

        return self.result

    def _create_content(self):
        """Create dialog content."""
        main_frame = ctk.CTkFrame(self.dialog, fg_color=self.colors["bg_card"], corner_radius=10)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Header
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))

        ctk.CTkLabel(header, text="🔧  Memory Pointer Offsets", font=("Segoe UI", 14, "bold"),
                     text_color=self.colors["text"]).pack(side="left")

        ctk.CTkLabel(main_frame,
                     text="Enter hex values (e.g. 0x042A01C8). Chains are comma-separated.",
                     font=("Segoe UI", 10), text_color=self.colors["text_secondary"]).pack(
            anchor="w", padx=20, pady=(0, 10))

        # Get current offsets
        offsets = self.config.get("memory_offsets", {})

        # Create scrollable frame for all offset entries
        scroll = ctk.CTkScrollableFrame(main_frame, fg_color="transparent", height=350)
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # HP Section
        hp_label = ctk.CTkLabel(scroll, text="HP (Life)", font=("Segoe UI", 11, "bold"),
                                text_color=self.colors["primary"])
        hp_label.pack(anchor="w", padx=10, pady=(5, 5))

        self._create_offset_row(scroll, "current_hp_base", "Current HP Base:",
                               offsets.get("current_hp_base", "0x042A01C8"))
        self._create_chain_row(scroll, "current_hp_chain", "Current HP Chain:",
                              offsets.get("current_hp_chain", ["0x0", "0x28", "0x70", "0x78", "0x504"]))
        self._create_offset_row(scroll, "max_hp_base", "Max HP Base:",
                               offsets.get("max_hp_base", "0x0443E9E8"))
        self._create_chain_row(scroll, "max_hp_chain", "Max HP Chain:",
                              offsets.get("max_hp_chain", ["0x30", "0x10", "0x0", "0x10", "0x0", "0x20", "0x2E8"]))

        # Separator
        ctk.CTkFrame(scroll, fg_color=self.colors["border"], height=1).pack(fill="x", padx=10, pady=10)

        # MP Section
        mp_label = ctk.CTkLabel(scroll, text="MP (Mana)", font=("Segoe UI", 11, "bold"),
                                text_color=self.colors["primary"])
        mp_label.pack(anchor="w", padx=10, pady=(5, 5))

        self._create_offset_row(scroll, "current_mp_base", "Current MP Base:",
                               offsets.get("current_mp_base", "0x0443E9E8"))
        self._create_chain_row(scroll, "current_mp_chain", "Current MP Chain:",
                              offsets.get("current_mp_chain", ["0x38", "0x8", "0x10", "0x20", "0x504"]))
        self._create_offset_row(scroll, "max_mp_base", "Max MP Base:",
                               offsets.get("max_mp_base", "0x0443E9E8"))
        self._create_chain_row(scroll, "max_mp_chain", "Max MP Chain:",
                              offsets.get("max_mp_chain", ["0x38", "0x10", "0x20", "0x28", "0x3C8"]))

        # Buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(5, 15))

        ctk.CTkButton(btn_frame, text="Cancel", command=self._on_cancel,
                      fg_color=self.colors["bg_hover"], hover_color=self.colors["border"],
                      text_color=self.colors["text"], width=100, height=32).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Save", command=self._on_save,
                      fg_color=self.colors["success"], hover_color="#2EA043",
                      text_color="#FFFFFF", width=100, height=32).pack(side="right")

        self.dialog.bind("<Escape>", lambda e: self._on_cancel())

    def _create_offset_row(self, parent, key: str, label: str, value: str):
        """Create a row for a single offset value."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(row, text=label, font=("Segoe UI", 10),
                     text_color=self.colors["text"], width=120, anchor="w").pack(side="left")

        entry = ctk.CTkEntry(row, font=("Consolas", 11), width=180, height=28,
                             fg_color=self.colors["bg_hover"], border_color=self.colors["border"],
                             text_color=self.colors["text"])
        entry.insert(0, value if isinstance(value, str) else hex(value))
        entry.pack(side="left", padx=(10, 0))
        self.entries[key] = entry

    def _create_chain_row(self, parent, key: str, label: str, chain: list):
        """Create a row for a pointer chain (comma-separated hex values)."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(row, text=label, font=("Segoe UI", 10),
                     text_color=self.colors["text"], width=120, anchor="w").pack(side="left")

        # Convert chain to comma-separated string
        if chain:
            chain_str = ", ".join(v if isinstance(v, str) else hex(v) for v in chain)
        else:
            chain_str = ""

        entry = ctk.CTkEntry(row, font=("Consolas", 10), width=300, height=28,
                             fg_color=self.colors["bg_hover"], border_color=self.colors["border"],
                             text_color=self.colors["text"])
        entry.insert(0, chain_str)
        entry.pack(side="left", padx=(10, 0))
        self.entries[key] = entry

    def _on_save(self):
        """Validate and save the offsets."""
        try:
            result = {}

            # Parse base offsets
            for key in ["current_hp_base", "max_hp_base", "current_mp_base", "max_mp_base"]:
                value = self.entries[key].get().strip()
                # Validate it's a valid hex
                int(value, 16)
                result[key] = value

            # Parse chains
            for key in ["current_hp_chain", "max_hp_chain", "current_mp_chain", "max_mp_chain"]:
                chain_str = self.entries[key].get().strip()
                if chain_str:
                    parts = [p.strip() for p in chain_str.split(",")]
                    # Validate each part is valid hex
                    for p in parts:
                        int(p, 16)
                    result[key] = parts
                else:
                    result[key] = []

            self.result = result
            self.dialog.destroy()

        except ValueError as e:
            # Show error - invalid hex value
            error_label = ctk.CTkLabel(self.dialog, text="❌ Invalid hex value! Use format: 0x1234",
                                       font=("Segoe UI", 10), text_color=self.colors["danger"])
            error_label.place(relx=0.5, rely=0.92, anchor="center")
            self.dialog.after(2000, error_label.destroy)

    def _on_cancel(self):
        """Cancel and close dialog."""
        self.result = None
        self.dialog.destroy()


# Convenience functions
def show_info(parent, title: str, message: str, colors: Optional[dict] = None) -> bool:
    return CustomDialog(parent, title, message, "info", "ok", colors).show()

def show_warning(parent, title: str, message: str, colors: Optional[dict] = None) -> bool:
    return CustomDialog(parent, title, message, "warning", "ok", colors).show()

def show_error(parent, title: str, message: str, colors: Optional[dict] = None) -> bool:
    return CustomDialog(parent, title, message, "error", "ok", colors).show()

def ask_yes_no(parent, title: str, message: str, colors: Optional[dict] = None) -> Optional[bool]:
    return CustomDialog(parent, title, message, "question", "yes_no", colors).show()
