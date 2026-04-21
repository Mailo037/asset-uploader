#!/usr/bin/env python3
"""
Roblox Asset Uploader - ASSET_CORE Terminal v2.04
Modern Multi-View GUI based on CustomTkinter.
"""

import os
import threading
import subprocess
import platform
import sys
from unittest.mock import MagicMock

# --- WORKAROUND FOR DARKDETECT HANG ---
# On some systems, darkdetect (used by customtkinter) can hang during theme detection.
# We mock it here to ensure the GUI starts immediately.
try:
    mock_darkdetect = MagicMock()
    mock_darkdetect.theme.return_value = "Dark"
    mock_darkdetect.isDark.return_value = True
    mock_darkdetect.isLight.return_value = False
    sys.modules["darkdetect"] = mock_darkdetect
except Exception:
    pass
# --------------------------------------

import customtkinter as ctk
from tkinter import filedialog, messagebox
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure the modern look (Dark mode, custom accent)
ctk.set_appearance_mode("Dark")

# ASSET_CORE Color Palette
BG_COLOR = "#09090b"           # zinc-950
SIDEBAR_COLOR = "#18181b"      # zinc-900
SURFACE_COLOR = "#27272a"      # zinc-800
ACCENT_CYAN = "#00f2ff"        # primary-fixed
ACCENT_PURPLE = "#dcb8ff"      # secondary
TEXT_MAIN = "#e5e2e1"          # on-background
TEXT_MUTED = "#a1a1aa"         # zinc-400

# Set default scaling for modern displays
ctk.set_widget_scaling(1.1)
ctk.set_window_scaling(1.1)

class AssetCoreGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Asset Uploader")
        self.geometry("1100x700")
        self.minsize(950, 600)
        self.configure(fg_color=BG_COLOR)
        
        # Grid layout: Sidebar (0) and Main Content (1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.target_path = ""
        self.frames = {}
        self.current_frame = None

        self._build_sidebar()
        
        # Main container for the views
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Build functional view
        self._build_upload_center()

        self._load_env_defaults()
        
        # Start on Upload Center by default
        self.select_frame_by_name("upload")

    # --- Navigation Logic ---
    
    def select_frame_by_name(self, name):
        """Switches the active view in the main container."""
        # Update button colors
        for btn_name, btn in self.nav_buttons.items():
            if btn_name == name:
                btn.configure(fg_color="#1e293b", text_color=ACCENT_CYAN) # zinc-800-ish
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_MUTED)

        # Show selected frame
        if self.current_frame:
            self.current_frame.grid_forget()
            
        self.current_frame = self.frames[name]
        self.current_frame.grid(row=0, column=0, sticky="nsew")

    # --- UI Builders ---

    def _build_sidebar(self):
        """Builds the left sidebar navigation."""
        self.sidebar = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color=SIDEBAR_COLOR, border_width=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(2, weight=1) # Push footer down

        # Brand Header
        brand_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, padx=20, pady=(30, 25), sticky="w")
        
        ctk.CTkLabel(brand_frame, text="ASSET_CORE", font=ctk.CTkFont(family="Inter", size=22, weight="bold"), text_color=ACCENT_CYAN).pack(anchor="w")

        # New Upload Button (Active View)
        self.upload_btn = ctk.CTkButton(
            self.sidebar, text="☁️ UPLOAD CENTER", font=ctk.CTkFont(family="Inter", size=13, weight="bold"), 
            fg_color="#1a2e33", border_color=ACCENT_CYAN, border_width=1, 
            text_color=ACCENT_CYAN, hover_color="#244147", height=40,
            command=lambda: self.select_frame_by_name("upload")
        )
        self.upload_btn.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        self.nav_buttons = {"upload": self.upload_btn}

        # Footer Navigation (Simplified)
        footer_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=20)
        
        ctk.CTkButton(footer_frame, text="⚙️ SETTINGS", font=ctk.CTkFont(family="Inter"), fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURFACE_COLOR, anchor="w").pack(fill="x", pady=2)

    # --- View: Upload Center (Functional) ---

    def _build_upload_center(self):
        """Builds the functional Upload Center view."""
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["upload"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # Header
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        ctk.CTkLabel(header_frame, text="Upload Center", font=ctk.CTkFont(family="Inter", size=28, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(header_frame, text="Stage and transfer assets to Roblox.", font=ctk.CTkFont(family="Inter"), text_color=TEXT_MUTED).pack(anchor="w")

        # Configuration Container (Glass panel look)
        config_frame = ctk.CTkFrame(frame, fg_color=SIDEBAR_COLOR, corner_radius=12, border_width=1, border_color=SURFACE_COLOR)
        config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        config_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Column 1: API & Target
        col1 = ctk.CTkFrame(config_frame, fg_color="transparent")
        col1.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        ctk.CTkLabel(col1, text="API Key", font=ctk.CTkFont(family="Inter", weight="bold")).pack(anchor="w")
        self.api_key_entry = ctk.CTkEntry(col1, show="*", placeholder_text="Roblox API Key", font=ctk.CTkFont(family="Inter"), fg_color=BG_COLOR, border_color=SURFACE_COLOR)
        self.api_key_entry.pack(fill="x", pady=(5, 15))
        
        ctk.CTkLabel(col1, text="Target Asset", font=ctk.CTkFont(family="Inter", weight="bold")).pack(anchor="w")
        target_btns = ctk.CTkFrame(col1, fg_color="transparent")
        target_btns.pack(fill="x", pady=(5, 5))
        ctk.CTkButton(target_btns, text="📄 File", font=ctk.CTkFont(family="Inter"), width=80, fg_color=SURFACE_COLOR, hover_color="#3f3f46", command=self._browse_file).pack(side="left", padx=(0, 5))
        ctk.CTkButton(target_btns, text="📁 Folder", font=ctk.CTkFont(family="Inter"), width=80, fg_color=SURFACE_COLOR, hover_color="#3f3f46", command=self._browse_folder).pack(side="left")
        self.target_label = ctk.CTkLabel(col1, text="No target selected...", text_color=TEXT_MUTED, font=ctk.CTkFont(family="Inter", slant="italic"))
        self.target_label.pack(anchor="w")

        # Column 2: Details
        col2 = ctk.CTkFrame(config_frame, fg_color="transparent")
        col2.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        
        ctk.CTkLabel(col2, text="Creator Settings", font=ctk.CTkFont(family="Inter", weight="bold")).pack(anchor="w")
        creator_frame = ctk.CTkFrame(col2, fg_color="transparent")
        creator_frame.pack(fill="x", pady=(5, 15))
        self.creator_type_menu = ctk.CTkOptionMenu(creator_frame, values=["user", "group"], font=ctk.CTkFont(family="Inter"), width=80, fg_color=BG_COLOR, button_color=SURFACE_COLOR)
        self.creator_type_menu.pack(side="left", padx=(0, 5))
        self.creator_id_entry = ctk.CTkEntry(creator_frame, placeholder_text="ID", font=ctk.CTkFont(family="Inter"), fg_color=BG_COLOR, border_color=SURFACE_COLOR)
        self.creator_id_entry.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(col2, text="Asset Type", font=ctk.CTkFont(family="Inter", weight="bold")).pack(anchor="w")
        self.asset_type_menu = ctk.CTkOptionMenu(col2, values=["Decal", "Image", "Model", "Audio", "Video"], font=ctk.CTkFont(family="Inter"), fg_color=BG_COLOR, button_color=SURFACE_COLOR)
        self.asset_type_menu.pack(fill="x", pady=(5, 0))

        # Column 3: Switches & Action
        col3 = ctk.CTkFrame(config_frame, fg_color="transparent")
        col3.grid(row=0, column=2, padx=20, pady=20, sticky="nsew")
        
        self.dry_run_switch = ctk.CTkSwitch(col3, text="Dry Run (Test Only)", font=ctk.CTkFont(family="Inter"), progress_color=ACCENT_CYAN)
        self.dry_run_switch.pack(anchor="w", pady=(20, 10))
        self.no_pixelfix_switch = ctk.CTkSwitch(col3, text="Disable Pixelfix", font=ctk.CTkFont(family="Inter"), progress_color=ACCENT_CYAN)
        self.no_pixelfix_switch.pack(anchor="w", pady=(0, 20))

        self.start_btn = ctk.CTkButton(
            col3, text="INITIATE UPLOAD", font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
            fg_color=ACCENT_CYAN, text_color=BG_COLOR, hover_color="#06b6d4",
            height=45, command=self._start_upload
        )
        self.start_btn.pack(fill="x", side="bottom")

        # Terminal Output
        term_frame = ctk.CTkFrame(frame, fg_color=BG_COLOR, corner_radius=8, border_width=1, border_color=SURFACE_COLOR)
        term_frame.grid(row=2, column=0, sticky="nsew")
        term_frame.grid_columnconfigure(0, weight=1)
        term_frame.grid_rowconfigure(1, weight=1)
        
        term_header = ctk.CTkFrame(term_frame, fg_color=SIDEBAR_COLOR, height=30, corner_radius=8)
        term_header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(term_header, text=">_ UPLOAD_LOG", font=ctk.CTkFont(family="Courier", size=12), text_color=TEXT_MUTED).pack(side="left", padx=10)

        self.console_text = ctk.CTkTextbox(
            term_frame, font=ctk.CTkFont(family="Inter", size=13), 
            text_color=ACCENT_CYAN, fg_color="transparent"
        )
        self.console_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.console_text.configure(state="disabled")

    # --- Mockup Views Removed as requested ---


    # --- Logic Methods (from old gui.py) ---

    def _load_env_defaults(self):
        """Loads default values from .env into the UI fields."""
        if os.getenv("ROBLOX_API_KEY"):
            self.api_key_entry.insert(0, os.getenv("ROBLOX_API_KEY"))
        if os.getenv("USER_ID"):
            self.creator_id_entry.insert(0, os.getenv("USER_ID"))
            self.creator_type_menu.set("user")
        elif os.getenv("GROUP_ID"):
            self.creator_id_entry.insert(0, os.getenv("GROUP_ID"))
            self.creator_type_menu.set("group")

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Select Asset File")
        if path:
            self.target_path = path
            self.target_label.configure(text=f"...{path[-40:]}" if len(path) > 40 else path, text_color=TEXT_MAIN)

    def _browse_folder(self):
        path = filedialog.askdirectory(title="Select Asset Directory")
        if path:
            self.target_path = path
            self.target_label.configure(text=f"...{path[-40:]}" if len(path) > 40 else path, text_color=TEXT_MAIN)

    def _log(self, message):
        """Appends text to the console output area thread-safely."""
        self.console_text.configure(state="normal")
        self.console_text.insert("end", message + "\n")
        self.console_text.yview("end")
        self.console_text.configure(state="disabled")

    def _start_upload(self):
        """Prepares and runs the upload CLI command in a separate thread."""
        target = self.target_path
        if not target:
            messagebox.showerror("Error", "Please select a file or folder first.")
            return

        api_key = self.api_key_entry.get()
        creator_id = self.creator_id_entry.get()
        if not creator_id:
            messagebox.showerror("Error", "Please provide a Creator ID.")
            return

        # Build command array using the current python interpreter
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploader.py")
        cmd = [sys.executable, script_path]
        
        if api_key:
            cmd.extend(["--key", api_key])
        
        if self.creator_type_menu.get() == "user":
            cmd.extend(["--user-id", creator_id])
        else:
            cmd.extend(["--group-id", creator_id])

        cmd.extend(["--asset-type", self.asset_type_menu.get()])

        if self.dry_run_switch.get() == 1:
            cmd.append("--dry-run")
            
        if self.no_pixelfix_switch.get() == 1:
            cmd.append("--no-pixelfix")

        cmd.append(target)

        # Disable button and clear console
        self.start_btn.configure(state="disabled", text="UPLOADING...")
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")
        
        self._log("=== ASSET_CORE INITIALIZING UPLOAD ===")
        self._log(f"> {' '.join([c if c != api_key else '***' for c in cmd])}\n")

        # Run via thread to prevent GUI freezing
        threading.Thread(target=self._run_subprocess, args=(cmd,), daemon=True).start()

    def _run_subprocess(self, cmd):
        """Executes the CLI command and captures its output safely."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding='utf-8', env=env, creationflags=creationflags
            )

            for line in process.stdout:
                self.after(0, self._log, line.rstrip())

            process.wait()
            self.after(0, self._log, f"\n=== Process finished with exit code {process.returncode} ===")

        except Exception as e:
            self.after(0, self._log, f"\nError executing script: {e}")
            
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal", text="INITIATE UPLOAD"))

if __name__ == "__main__":
    app = AssetCoreGUI()
    app.mainloop()