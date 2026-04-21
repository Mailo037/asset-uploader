#!/usr/bin/env python3
"""
Roblox Asset Uploader - Modern Graphical User Interface
Features a sleek dark theme inspired by Blur-AutoClicker.
"""

import os
import threading
import subprocess
import platform
import customtkinter as ctk
from tkinter import filedialog, messagebox
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure the modern look (Dark mode, custom accent)
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class RobloxUploaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Roblox Asset Uploader")
        self.geometry("900x600")
        self.minsize(800, 500)
        
        # Two-pane layout: Sidebar (0) and Main Content (1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.target_path = ""
        
        self._build_sidebar()
        self._build_main()
        self._load_env_defaults()

    def _build_sidebar(self):
        """Builds the left sidebar containing all settings."""
        # Zinc 900 background for sidebar
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="#18181b") 
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1) # Pushes everything to the top

        # Title
        title_label = ctk.CTkLabel(self.sidebar, text="UPLOADER", font=ctk.CTkFont(size=24, weight="bold"), text_color="#ffffff")
        title_label.grid(row=0, column=0, padx=20, pady=(30, 25), sticky="w")

        # 1. API Key
        ctk.CTkLabel(self.sidebar, text="API Key", font=ctk.CTkFont(size=12, weight="bold"), text_color="#a1a1aa").grid(row=1, column=0, sticky="w", padx=20, pady=(10, 0))
        self.api_key_entry = ctk.CTkEntry(self.sidebar, show="*", placeholder_text="Roblox API Key", border_width=1, fg_color="#27272a", border_color="#3f3f46")
        self.api_key_entry.grid(row=2, column=0, sticky="ew", padx=20, pady=(5, 15))

        # 2. Creator Type & ID
        ctk.CTkLabel(self.sidebar, text="Creator Type & ID", font=ctk.CTkFont(size=12, weight="bold"), text_color="#a1a1aa").grid(row=3, column=0, sticky="w", padx=20, pady=(5, 0))
        
        id_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        id_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=(5, 15))
        id_frame.columnconfigure(1, weight=1)
        
        self.creator_type_menu = ctk.CTkOptionMenu(id_frame, values=["user", "group"], width=80, fg_color="#27272a", button_color="#3f3f46")
        self.creator_type_menu.grid(row=0, column=0, sticky="w", padx=(0, 5))
        
        self.creator_id_entry = ctk.CTkEntry(id_frame, placeholder_text="ID", border_width=1, fg_color="#27272a", border_color="#3f3f46")
        self.creator_id_entry.grid(row=0, column=1, sticky="ew")

        # 3. Asset Type
        ctk.CTkLabel(self.sidebar, text="Asset Type", font=ctk.CTkFont(size=12, weight="bold"), text_color="#a1a1aa").grid(row=5, column=0, sticky="w", padx=20, pady=(5, 0))
        self.asset_type_menu = ctk.CTkOptionMenu(self.sidebar, values=["Decal", "Image", "Model", "Audio", "Video"], fg_color="#27272a", button_color="#3f3f46")
        self.asset_type_menu.grid(row=6, column=0, sticky="ew", padx=20, pady=(5, 25))

        # 4. Switches (Blur style)
        self.dry_run_switch = ctk.CTkSwitch(self.sidebar, text="Dry Run (Test)", progress_color="#6366f1", text_color="#d4d4d8")
        self.dry_run_switch.grid(row=7, column=0, sticky="w", padx=20, pady=10)
        
        self.no_pixelfix_switch = ctk.CTkSwitch(self.sidebar, text="Disable Pixelfix", progress_color="#6366f1", text_color="#d4d4d8")
        self.no_pixelfix_switch.grid(row=8, column=0, sticky="nw", padx=20, pady=10)

    def _build_main(self):
        """Builds the main content area (Right side)."""
        # Zinc 950 background for main area
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#09090b") 
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        # Target Selection Frame
        target_frame = ctk.CTkFrame(self.main_frame, fg_color="#18181b", corner_radius=10)
        target_frame.grid(row=0, column=0, sticky="ew", padx=30, pady=(30, 20))
        target_frame.columnconfigure(2, weight=1)

        self.btn_file = ctk.CTkButton(target_frame, text="Select File", command=self._browse_file, width=110, fg_color="#3f3f46", hover_color="#52525b")
        self.btn_file.grid(row=0, column=0, padx=15, pady=15)
        
        self.btn_folder = ctk.CTkButton(target_frame, text="Select Folder", command=self._browse_folder, width=110, fg_color="#3f3f46", hover_color="#52525b")
        self.btn_folder.grid(row=0, column=1, padx=(0, 15), pady=15)
        
        self.target_label = ctk.CTkLabel(target_frame, text="No target selected...", text_color="#71717a", font=ctk.CTkFont(slant="italic"))
        self.target_label.grid(row=0, column=2, sticky="w", padx=15)

        # Big Action Button
        self.start_btn = ctk.CTkButton(
            self.main_frame, 
            text="START UPLOAD", 
            command=self._start_upload, 
            font=ctk.CTkFont(size=18, weight="bold"),
            height=60,
            corner_radius=8,
            fg_color="#6366f1", # Indigo accent color
            hover_color="#4f46e5"
        )
        self.start_btn.grid(row=1, column=0, sticky="ew", padx=30, pady=10)

        # Console Output
        self.console_text = ctk.CTkTextbox(
            self.main_frame, 
            corner_radius=8, 
            font=ctk.CTkFont("Consolas", size=13), 
            text_color="#a3e635", # Hacker green text
            fg_color="#18181b", 
            border_width=1, 
            border_color="#27272a"
        )
        self.console_text.grid(row=2, column=0, sticky="nsew", padx=30, pady=(20, 30))
        self.console_text.configure(state="disabled")

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
            self.target_label.configure(text=f"...{path[-50:]}" if len(path) > 50 else path, text_color="#e4e4e7", font=ctk.CTkFont(slant="roman"))

    def _browse_folder(self):
        path = filedialog.askdirectory(title="Select Asset Directory")
        if path:
            self.target_path = path
            self.target_label.configure(text=f"...{path[-50:]}" if len(path) > 50 else path, text_color="#e4e4e7", font=ctk.CTkFont(slant="roman"))

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

        # Build command array
        cmd = ["python", "uploader.py"]
        
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
        
        self._log("=== Starting Upload Process ===")
        self._log(f"> {' '.join([c if c != api_key else '***' for c in cmd])}\n")

        # Run via thread to prevent GUI freezing
        threading.Thread(target=self._run_subprocess, args=(cmd,), daemon=True).start()

    def _run_subprocess(self, cmd):
        """Executes the CLI command and captures its output safely."""
        
        # Enforce UTF-8 to prevent the UnicodeEncodeError crash from 'rich' tables
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        # Hide the black CMD window completely on Windows
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                env=env,
                creationflags=creationflags
            )

            for line in process.stdout:
                self.after(0, self._log, line.rstrip())

            process.wait()
            self.after(0, self._log, f"\n=== Process finished with exit code {process.returncode} ===")

        except Exception as e:
            self.after(0, self._log, f"\nError executing script: {e}")
            
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal", text="START UPLOAD"))

if __name__ == "__main__":
    app = RobloxUploaderGUI()
    app.mainloop()