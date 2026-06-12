"""
Toast notification system for POE2 Flask Bot GUI.
Provides non-intrusive, auto-dismissing notifications.
"""

import customtkinter as ctk
from typing import Literal


class ToastNotification:
    """Toast notification that appears in the corner of a window."""
    
    active_toasts = []  # Track active toasts for stacking
    
    def __init__(
        self,
        parent,
        message: str,
        duration: int = 3000,
        notification_type: Literal["success", "info", "warning", "error"] = "info",
        position: Literal["top-right", "top-left", "bottom-right", "bottom-left"] = "top-right"
    ):
        self.parent = parent
        self.message = message
        self.duration = duration
        self.notification_type = notification_type
        self.position = position
        self.toast_frame = None
        self.after_id = None
        
        self.colors = {
            "success": {"bg": "#00D9A3", "fg": "#FFFFFF", "icon": "✓"},
            "info": {"bg": "#6C5CE7", "fg": "#FFFFFF", "icon": "ℹ"},
            "warning": {"bg": "#FFA500", "fg": "#1A1A2E", "icon": "⚠"},
            "error": {"bg": "#FF4757", "fg": "#FFFFFF", "icon": "✕"}
        }
    
    def show(self):
        """Display the toast notification."""
        color_scheme = self.colors.get(self.notification_type, self.colors["info"])
        
        self.toast_frame = ctk.CTkFrame(self.parent, fg_color=color_scheme["bg"], corner_radius=8)
        
        content = ctk.CTkFrame(self.toast_frame, fg_color="transparent")
        content.pack(padx=15, pady=10, fill="both", expand=True)
        
        ctk.CTkLabel(content, text=color_scheme["icon"], font=("Segoe UI", 16, "bold"),
                     text_color=color_scheme["fg"]).pack(side="left", padx=(0, 10))
        
        ctk.CTkLabel(content, text=self.message, font=("Segoe UI", 12),
                     text_color=color_scheme["fg"], wraplength=250, justify="left").pack(side="left", fill="both", expand=True)
        
        self._position_toast()
        ToastNotification.active_toasts.append(self)
        
        if self.duration > 0:
            self.after_id = self.parent.after(self.duration, self.dismiss)
        
        self.toast_frame.bind("<Button-1>", lambda e: self.dismiss())
    
    def _position_toast(self):
        """Position the toast in the specified corner with stacking."""
        self.toast_frame.update_idletasks()
        
        toast_width = self.toast_frame.winfo_reqwidth()
        toast_height = self.toast_frame.winfo_reqheight()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        
        padding = 20
        toast_index = len(ToastNotification.active_toasts)
        vertical_offset = toast_index * (toast_height + 10)
        
        if self.position == "top-right":
            x = parent_width - toast_width - padding
            y = padding + vertical_offset
        elif self.position == "top-left":
            x, y = padding, padding + vertical_offset
        elif self.position == "bottom-right":
            x = parent_width - toast_width - padding
            y = parent_height - toast_height - padding - vertical_offset
        else:
            x, y = padding, parent_height - toast_height - padding - vertical_offset
        
        self.toast_frame.place(x=x, y=y)
    
    def dismiss(self):
        """Dismiss the toast notification."""
        if self.after_id:
            self.parent.after_cancel(self.after_id)
            self.after_id = None
        
        if self in ToastNotification.active_toasts:
            ToastNotification.active_toasts.remove(self)
        
        if self.toast_frame:
            self.toast_frame.destroy()
            self.toast_frame = None
        
        for toast in ToastNotification.active_toasts:
            if toast.toast_frame and toast.toast_frame.winfo_exists():
                toast._position_toast()
