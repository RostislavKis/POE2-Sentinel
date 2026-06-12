"""
Coordinate Picker Module - Visual tool to pick screen regions for HP/Mana.
Uses modern overlay with rectangle drawing.
"""

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageTk
import mss
import time

from flask_bot import load_config, save_config
from custom_dialog import show_info, show_error, ask_yes_no
from toast_notification import ToastNotification


class RegionPicker:
    """
    Visual picker for selecting screen regions (rectangle).
    Used for HP/Mana capture areas.
    """

    def __init__(self, region_type: str, parent=None):
        self.region_type = region_type
        self.parent = parent
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.result = None
        self._owns_root = False

        # Colors for different region types
        self.colors = {
            "life": "#FF4757",
            "mana": "#6C5CE7"
        }

    def show(self) -> dict | None:
        """Show picker and return region dict or None if cancelled."""
        # Take screenshot
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            self.screenshot = sct.grab(monitor)

        # Create fullscreen window. When a parent root already exists, use a
        # Toplevel child: creating a second tk.Tk() root and destroying it
        # tears down the shared Tcl state and closes the whole application.
        if self.parent is not None:
            self.root = tk.Toplevel(self.parent)
        else:
            self.root = tk.Tk()
            self._owns_root = True

        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.configure(cursor="cross")

        # Convert and darken screenshot
        img = Image.frombytes("RGB", self.screenshot.size, self.screenshot.bgra, "raw", "BGRX")
        img = img.point(lambda p: int(p * 0.6))
        # Bind to this window's interpreter; otherwise the image attaches to the
        # main GUI's Tk root and won't render here (canvas shows a white screen).
        self.photo = ImageTk.PhotoImage(img, master=self.root)

        # Create canvas
        self.canvas = tk.Canvas(
            self.root,
            width=self.screenshot.width,
            height=self.screenshot.height,
            highlightthickness=0
        )
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Draw instruction panel
        self._draw_instructions()

        # Bind events
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.root.bind("<Escape>", self._on_escape)

        # A standalone Tk root needs its own event loop; a Toplevel child
        # instead grabs input and waits until it is destroyed.
        if self._owns_root:
            self.root.mainloop()
        else:
            self.root.grab_set()
            self.root.focus_force()
            self.root.wait_window()

        return self.result

    def _draw_instructions(self):
        """Draw instruction panel."""
        cx = self.screenshot.width // 2
        color = self.colors.get(self.region_type, "#6C5CE7")

        # Background box
        self.canvas.create_rectangle(
            cx - 300, 20, cx + 300, 100,
            fill="#1a1a2e", outline=color, width=2
        )

        # Text
        self.canvas.create_text(
            cx, 45,
            text=f"Draw a rectangle around the {self.region_type.upper()} value",
            fill=color, font=("Segoe UI", 16, "bold")
        )
        self.canvas.create_text(
            cx, 75,
            text="Click and drag to select • Press ESC to cancel",
            fill="#888888", font=("Segoe UI", 11)
        )

    def _on_mouse_down(self, event):
        """Handle mouse button press."""
        self.start_x = event.x
        self.start_y = event.y

        if self.rect_id:
            self.canvas.delete(self.rect_id)

        color = self.colors.get(self.region_type, "#6C5CE7")
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline=color, width=3
        )

    def _on_mouse_drag(self, event):
        """Handle mouse drag."""
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_mouse_up(self, event):
        """Handle mouse release - validate and save."""
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(event.x - self.start_x)
        height = abs(event.y - self.start_y)

        if width < 20 or height < 10:
            # Too small, let user try again
            if self.rect_id:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
            return

        self.result = {"top": top, "left": left, "width": width, "height": height}
        self.root.destroy()

    def _on_escape(self, event):
        """Cancel selection."""
        self.result = None
        self.root.destroy()


def pick_region(region_type: str, parent=None) -> dict | None:
    """
    Open the region picker for the specified type.

    Args:
        region_type: 'life' or 'mana'
        parent: Existing Tk root to attach to. When provided, the picker uses
            a Toplevel child window instead of a second Tk root.

    Returns:
        Region dict with top, left, width, height or None if cancelled
    """
    picker = RegionPicker(region_type, parent=parent)
    return picker.show()
