import os
import subprocess
import threading
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Theme matching your premium UI image
BG_COLOR = "#111622"         # Deep dark tech background
CARD_COLOR = "#1a2130"       # File info card background
ACCENT_BLUE = "#3b82f6"      # Bright blue accent buttons/bars
TEXT_MUTED = "#64748b"       # Muted gray text
SUCCESS_GREEN = "#10b981"    # Green confirmation text

class ChucnyPremiumPatcher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ChucnyServer Patcher")
        self.geometry("700x700") # Standard compact view
        self.configure(fg_color=BG_COLOR)
        self.resizable(False, False)
        self.apk_path = ""
        self.process = None
        self.logs_visible = False

        # --- LOGO / ICON ---
        self.icon_label = ctk.CTkLabel(self, text="⚡", font=("Arial", 36), text_color=ACCENT_BLUE)
        self.icon_label.pack(pady=(40, 5))

        # --- HEADERS ---
        self.title_label = ctk.CTkLabel(self, text="ChucnyServer Patcher", font=("Segoe UI", 22, "bold"), text_color="#ffffff")
        self.title_label.pack(pady=2)

        self.subtitle_label = ctk.CTkLabel(self, text="APK Patcher for removing Certificate Pinning", font=("Segoe UI", 13), text_color=TEXT_MUTED)
        self.subtitle_label.pack(pady=(0, 25))

        # --- SELECT BOX (DASHED FRAME) ---
        self.drop_frame = ctk.CTkFrame(self, fg_color="transparent", width=420, height=160, corner_radius=12, border_width=1, border_color="#334155")
        self.drop_frame.pack_propagate(False)
        self.drop_frame.pack(pady=15)
        self.drop_frame.bind("<Button-1>", lambda e: self.select_apk_manually())

        self.upload_icon = ctk.CTkLabel(self.drop_frame, text="📤", font=("Arial", 24), text_color=TEXT_MUTED)
        self.upload_icon.pack(pady=(40, 5))
        self.upload_icon.bind("<Button-1>", lambda e: self.select_apk_manually())

        self.box_main_text = ctk.CTkLabel(self.drop_frame, text="Select APK...", font=("Segoe UI", 14, "bold"), text_color="#ffffff")
        self.box_main_text.pack(pady=2)
        self.box_main_text.bind("<Button-1>", lambda e: self.select_apk_manually())

        self.box_sub_text = ctk.CTkLabel(self.drop_frame, text="or click to browse your files", font=("Segoe UI", 12), text_color=TEXT_MUTED)
        self.box_sub_text.pack(pady=(0, 20))
        self.box_sub_text.bind("<Button-1>", lambda e: self.select_apk_manually())

        # --- FILE INFO CARD (HIDDEN BY DEFAULT) ---
        self.file_card = ctk.CTkFrame(self, fg_color=CARD_COLOR, width=420, height=70, corner_radius=10)
        self.file_card.pack_propagate(False)
        
        self.file_icon = ctk.CTkLabel(self.file_card, text="🤖", font=("Arial", 20), text_color=ACCENT_BLUE)
        self.file_icon.pack(side="left", padx=(20, 10))
        
        self.file_name_label = ctk.CTkLabel(self.file_card, text="No file selected", font=("Segoe UI", 13, "bold"), text_color="#ffffff", anchor="w")
        self.file_name_label.pack(side="top", fill="x", padx=5, pady=(15, 0))
        
        self.file_size_label = ctk.CTkLabel(self.file_card, text="0.00 MB", font=("Segoe UI", 11), text_color=TEXT_MUTED, anchor="w")
        self.file_size_label.pack(side="top", fill="x", padx=5)

        # --- PROGRESS SECTION ---
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent", width=420)
        self.progress_frame.pack(pady=(25, 5))

        self.progress_status = ctk.CTkLabel(self.progress_frame, text="Waiting for APK...", font=("Segoe UI", 12), text_color=TEXT_MUTED)
        self.progress_status.pack(side="left")

        self.progress_percent = ctk.CTkLabel(self.progress_frame, text="0%", font=("Segoe UI", 12), text_color=TEXT_MUTED)
        self.progress_percent.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(self, width=420, height=6, fg_color="#1e293b", progress_color=ACCENT_BLUE, corner_radius=3)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0, 15))

        # --- MAIN ACTION BUTTON ---
        self.btn_patch = ctk.CTkButton(
            self, 
            text="Start Patching Process", 
            font=("Segoe UI", 15, "bold"),
            fg_color=ACCENT_BLUE,
            hover_color="#2563eb",
            text_color="#ffffff",
            width=420,
            height=48,
            corner_radius=8,
            state="disabled",
            command=self.start_patch_thread
        )
        self.btn_patch.pack(pady=5)

        # --- EXTRA LOGS SECTION (EXPANDABLE TERMINAL) ---
        self.btn_toggle_logs = ctk.CTkButton(self, text="▶ Show Live Terminal Logs", font=("Segoe UI", 11), fg_color="transparent", hover_color="#1e293b", text_color=TEXT_MUTED, width=150, command=self.toggle_logs)
        self.btn_toggle_logs.pack(pady=5)

        self.terminal_frame = ctk.CTkFrame(self, fg_color="#0f172a", width=420, height=180, corner_radius=6, border_width=1, border_color="#1e293b")
        self.terminal_text = ctk.CTkTextbox(self.terminal_frame, font=("Consolas", 11), text_color="#38bdf8", fg_color="#0f172a")
        self.terminal_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_to_terminal("[SYSTEM] Ready. Waiting for file intake...\n")

        # --- SUCCESS FOOTER ---
        self.success_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 12, "bold"), text_color=SUCCESS_GREEN)
        self.success_label.pack(pady=5)

    def toggle_logs(self):
        if not self.logs_visible:
            self.geometry("580x820")
            self.terminal_frame.pack(pady=10, before=self.success_label)
            self.btn_toggle_logs.configure(text="▼ Hide Terminal Logs")
            self.logs_visible = True
        else:
            self.terminal_frame.pack_forget()
            self.geometry("580x620")
            self.btn_toggle_logs.configure(text="▶ Show Terminal Logs")
            self.logs_visible = False

    def log_to_terminal(self, text):
        self.terminal_text.insert("end", text)
        self.terminal_text.see("end")

    def select_apk_manually(self):
        initial_dir = os.path.expanduser("~")
        self.apk_path = filedialog.askopenfilename(initialdir=initial_dir, title="Load Target Android Package", filetypes=[("Android Package", "*.apk")])
        
        if self.apk_path:
            filename = os.path.basename(self.apk_path)
            
            try:
                size_bytes = os.path.getsize(self.apk_path)
                size_mb = f"{size_bytes / (1024 * 1024):.2f} MB"
            except:
                size_mb = "Unknown Size"

            self.file_card.pack(pady=10, before=self.progress_frame)
            
            if len(filename) > 38:
                display_name = filename[:35] + "..."
            else:
                display_name = filename

            self.file_name_label.configure(text=display_name)
            self.file_size_label.configure(text=size_mb)
            
            self.log_to_terminal(f"[SYSTEM] Loaded target file: {self.apk_path}\n")
            self.btn_patch.configure(state="normal")
            self.success_label.configure(text="")

    def start_patch_thread(self):
        self.btn_patch.configure(state="disabled")
        self.drop_frame.unbind("<Button-1>")
        self.progress_status.configure(text="Running apk-mitm...")
        self.progress_percent.configure(text="15%")
        self.progress_bar.set(0.15)
        threading.Thread(target=self.run_background_patcher, daemon=True).start()

    def run_background_patcher(self):
        self.log_to_terminal("\n" + "="*60 + "\n")
        self.log_to_terminal("[MUTATION ORE] ENTRANTS ACTIVATED — INJECTING PIPELINES...\n")
        self.log_to_terminal("="*60 + "\n\n")

        is_windows = os.name == 'nt'
        cmd = ["npx", "apk-mitm", self.apk_path]

        try:
            startupinfo = None
            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                shell=is_windows,
                startupinfo=startupinfo,
                bufsize=1
            )
            
            while True:
                line = self.process.stdout.readline()
                if not line and self.process.poll() is not None:
                    break
                if line:
                    clean_line = line.replace('[2K', '').replace('[1G', '')
                    self.log_to_terminal(clean_line)
                    
                    if "Decoding" in clean_line:
                        self.progress_status.configure(text="Decompiling APK...")
                        self.progress_percent.configure(text="35%")
                        self.progress_bar.set(0.35)
                    elif "Applying patches" in clean_line:
                        self.progress_status.configure(text="Removing SSL pinning...")
                        self.progress_percent.configure(text="65%")
                        self.progress_bar.set(0.65)
                    elif "Encoding" in clean_line:
                        self.progress_status.configure(text="Finalizing APK...")
                        self.progress_percent.configure(text="85%")
                        self.progress_bar.set(0.85)
                    elif "Signing" in clean_line:
                        self.progress_status.configure(text="Signing APK...")
                        self.progress_percent.configure(text="95%")
                        self.progress_bar.set(0.95)

            if self.process.returncode == 0:
                self.progress_status.configure(text="Finalizing build...")
                self.progress_percent.configure(text="100%")
                self.progress_bar.set(1.0)
                self.success_label.configure(text="✓ Patch applied successfully! Optimized APK ready.")
                messagebox.showinfo("Success", "The modified unpinned APK has been successfully compiled next to your source file.")
            else:
                self.progress_status.configure(text="Process aborted.")
                self.progress_percent.configure(text="0%")
                self.progress_bar.set(0)
                messagebox.showerror("Lab Error", "The transformation workflow failed. View technical logs below.")
                
        except Exception as e:
            self.log_to_terminal(f"\n[EXCEPTION] Relay interface failure: {str(e)}\n")
            messagebox.showerror("Interface Error", str(e))
            
        self.btn_patch.configure(state="normal")
        self.drop_frame.bind("<Button-1>", lambda e: self.select_apk_manually())

if __name__ == "__main__":
    app = ChucnyPremiumPatcher()
    app.mainloop()
