import os
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class HexEditorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ChucnyServer Hex Editor")
        self.geometry("980x680")

        self.file_path = None
        self.file_data = bytearray()
        self.is_updating = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Control Panel
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.btn_open = ctk.CTkButton(self.top_frame, text="Open File", command=self.open_file, width=90)
        self.btn_open.pack(side="left", padx=5, pady=5)

        self.btn_save = ctk.CTkButton(self.top_frame, text="Save File", command=self.save_file, width=90)
        self.btn_save.pack(side="left", padx=5, pady=5)

        self.entry_goto = ctk.CTkEntry(self.top_frame, placeholder_text="Offset (Hex e.g. 18610)", width=160)
        self.entry_goto.pack(side="left", padx=5, pady=5)

        self.btn_goto = ctk.CTkButton(self.top_frame, text="Go To", command=self.go_to_offset, width=70)
        self.btn_goto.pack(side="left", padx=2, pady=5)

        self.lbl_info = ctk.CTkLabel(self.top_frame, text="No file loaded")
        self.lbl_info.pack(side="right", padx=5, pady=5)

        # Main Layout: Text Editor + Side Inspector Panel
        self.main_pane = ctk.CTkFrame(self)
        self.main_pane.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.main_pane.grid_columnconfigure(0, weight=4)
        self.main_pane.grid_columnconfigure(1, weight=1)
        self.main_pane.grid_rowconfigure(0, weight=1)

        # Editor View Area
        self.text_box = ctk.CTkTextbox(self.main_pane, font=("Courier New", 12))
        self.text_box.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="nsew")
        
        self.text_box.bind("<ButtonRelease-1>", self.on_cursor_select)
        self.text_box.bind("<KeyRelease>", self.on_key_release)

        # Inspector Panel
        self.inspector_frame = ctk.CTkFrame(self.main_pane)
        self.inspector_frame.grid(row=0, column=1, padx=(5, 0), pady=0, sticky="nsew")

        self.lbl_inspector_title = ctk.CTkLabel(self.inspector_frame, text="Data Inspector", font=("Arial", 14, "bold"))
        self.lbl_inspector_title.pack(padx=10, pady=(10, 5), anchor="w")

        # Encoding Selector Dropdown
        self.lbl_encoding = ctk.CTkLabel(self.inspector_frame, text="Text Format / Encoding:", font=("Arial", 11))
        self.lbl_encoding.pack(padx=10, pady=(5, 0), anchor="w")

        self.encoding_var = ctk.StringVar(value="ascii")
        self.encoding_dropdown = ctk.CTkOptionMenu(
            self.inspector_frame, 
            values=["ascii", "utf-8", "utf-16le", "shift_jis"],
            variable=self.encoding_var,
            command=lambda _: self.render_hex()
        )
        self.encoding_dropdown.pack(padx=10, pady=5, fill="x")

        self.lbl_format_info = ctk.CTkLabel(self.inspector_frame, text="Click a byte in the editor\nto inspect multiple formats.", justify="left", font=("Courier New", 11))
        self.lbl_format_info.pack(padx=10, pady=5, anchor="w")

    def open_file(self):
        path = filedialog.askopenfilename()
        if path:
            try:
                with open(path, "rb") as f:
                    self.file_data = bytearray(f.read())
                self.file_path = path
                self.lbl_info.configure(text=f"{os.path.basename(path)} ({len(self.file_data)} bytes)")
                self.render_hex()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def render_hex(self):
        self.is_updating = True
        self.text_box.delete("0.0", "end")
        hex_lines = []
        encoding = self.encoding_var.get()
        
        for i in range(0, len(self.file_data), 16):
            chunk = self.file_data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            
            # Decode using the selected encoding, replacing invalid sequences with dots
            try:
                decoded_str = chunk.decode(encoding, errors="replace")
                ascii_str = "".join(c if c.isprintable() and len(c) == 1 and c != "" else "." for c in decoded_str)
            except Exception:
                ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
                
            line = f"{i:08X}  {hex_str:<47}  |{ascii_str}|"
            hex_lines.append(line)
        self.text_box.insert("0.0", "\n".join(hex_lines))
        self.is_updating = False

    def go_to_offset(self):
        if not self.file_data:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        
        query = self.entry_goto.get().strip()
        try:
            target_offset = int(query, 16)
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid hexadecimal offset (e.g., 18610).")
            return

        if target_offset >= len(self.file_data):
            messagebox.showerror("Out of Bounds", f"Offset {query} exceeds file size ({len(self.file_data)} bytes).")
            return

        line_num = (target_offset // 16) + 1
        start_index = f"{line_num}.0"
        
        self.text_box.see(start_index)
        self.text_box.tag_remove("highlight", "1.0", "end")
        self.text_box.tag_add("highlight", start_index, f"{line_num}.8")
        self.text_box.tag_config("highlight", background="#3b8ed0", foreground="white")

    def on_cursor_select(self, event):
        if not self.file_data:
            return
        try:
            cursor_pos = self.text_box.index("insert")
            line_idx, col_idx = map(int, cursor_pos.split("."))
            
            if col_idx < 10 or col_idx > 57:
                return
            
            hex_char_offset = col_idx - 10
            byte_in_row = hex_char_offset // 3
            if byte_in_row >= 16:
                return

            file_offset = (line_idx - 1) * 16 + byte_in_row
            if file_offset >= len(self.file_data):
                return

            b = self.file_data[file_offset]
            encoding = self.encoding_var.get()
            
            snippet_bytes = self.file_data[file_offset:file_offset+4]
            try:
                decoded_text = snippet_bytes.decode(encoding, errors="replace")
            except Exception:
                decoded_text = "?"

            val_int8 = int.from_bytes(self.file_data[file_offset:file_offset+1], byteorder='little', signed=True)
            val_uint8 = b
            val_int16 = int.from_bytes(self.file_data[file_offset:file_offset+2], byteorder='little', signed=True) if file_offset + 2 <= len(self.file_data) else "N/A"
            val_uint16 = int.from_bytes(self.file_data[file_offset:file_offset+2], byteorder='little', signed=False) if file_offset + 2 <= len(self.file_data) else "N/A"
            val_int32 = int.from_bytes(self.file_data[file_offset:file_offset+4], byteorder='little', signed=True) if file_offset + 4 <= len(self.file_data) else "N/A"
            val_uint32 = int.from_bytes(self.file_data[file_offset:file_offset+4], byteorder='little', signed=False) if file_offset + 4 <= len(self.file_data) else "N/A"

            info_text = (
                f"Offset: 0x{file_offset:08X}\n\n"
                f"Format: {encoding}\n"
                f"Decoded: '{decoded_text}'\n"
                f"Hex:    0x{b:02X}\n"
                f"Binary: 0b{b:08b}\n"
                f"Int8:   {val_int8}\n"
                f"UInt8:  {val_uint8}\n"
                f"Int16:  {val_int16}\n"
                f"UInt16: {val_uint16}\n"
                f"Int32:  {val_int32}\n"
                f"UInt32: {val_uint32}"
            )
            self.lbl_format_info.configure(text=info_text)
        except Exception:
            pass

    def on_key_release(self, event):
        if self.is_updating or not self.file_data:
            return

        try:
            cursor_pos = self.text_box.index("insert")
            line_idx, col_idx = map(int, cursor_pos.split("."))
            
            line_start = f"{line_idx}.0"
            line_end = f"{line_idx}.end"
            line_text = self.text_box.get(line_start, line_end)
            
            if len(line_text) < 76:
                return

            offset_base = (line_idx - 1) * 16
            encoding = self.encoding_var.get()
            
            if 10 <= col_idx <= 57:
                hex_part = line_text[10:57]
                hex_tokens = hex_part.strip().split()
                
                byte_values = []
                for ht in hex_tokens[:16]:
                    try:
                        byte_values.append(int(ht, 16))
                    except ValueError:
                        return 
                
                while len(byte_values) < 16:
                    byte_values.append(0)

                try:
                    decoded_str = bytearray(byte_values).decode(encoding, errors="replace")
                    new_ascii = "".join(c if c.isprintable() and len(c) == 1 and c != "" else "." for c in decoded_str)
                except Exception:
                    new_ascii = "".join(chr(b) if 32 <= b <= 126 else "." for b in byte_values)
                
                self.is_updating = True
                current_insert = self.text_box.index("insert")
                
                ascii_start = f"{line_idx}.59"
                ascii_end = f"{line_idx}.75"
                self.text_box.delete(ascii_start, ascii_end)
                self.text_box.insert(ascii_start, f"|{new_ascii}|")
                
                self.text_box.mark_set("insert", current_insert)
                self.is_updating = False

            elif 60 <= col_idx <= 75:
                ascii_part = line_text[60:76].strip("|")
                try:
                    # Clean dots back to a safe placeholder byte for encoding translation
                    clean_ascii = ascii_part.replace(".", "\x00")
                    byte_values = list(clean_ascii.encode(encoding, errors="replace"))[:16]
                except Exception:
                    byte_values = [ord(c) if c != "." and 32 <= ord(c) <= 126 else 0 for c in ascii_part[:16]]
                
                while len(byte_values) < 16:
                    byte_values.append(0)

                new_hex = " ".join(f"{b:02X}" for b in byte_values)
                
                self.is_updating = True
                current_insert = self.text_box.index("insert")
                
                hex_start = f"{line_idx}.10"
                hex_end = f"{line_idx}.57"
                self.text_box.delete(hex_start, hex_end)
                self.text_box.insert(hex_start, f"{new_hex:<47}")
                
                self.text_box.mark_set("insert", current_insert)
                self.is_updating = False

            for i, b in enumerate(byte_values):
                target_idx = offset_base + i
                if target_idx < len(self.file_data):
                    self.file_data[target_idx] = b

        except Exception:
            self.is_updating = False

    def save_file(self):
        if not self.file_path:
            return
        
        content = self.text_box.get("0.0", "end").strip().split("\n")
        new_data = bytearray()
        
        try:
            for line in content:
                if not line.strip():
                    continue
                parts = line.split("  ")
                if len(parts) >= 2:
                    hex_bytes = parts[1].strip().split()
                    for hb in hex_bytes:
                        new_data.append(int(hb, 16))
            
            if len(new_data) != len(self.file_data):
                messagebox.showerror(
                    "Size Mismatch Error", 
                    f"File length changed! Original: {len(self.file_data)} bytes, Modified: {len(new_data)} bytes.\n"
                    "Adding or removing bytes is disabled to keep the file size fixed."
                )
                return

            with open(self.file_path, "wb") as f:
                f.write(new_data)
            
            self.file_data = new_data
            messagebox.showinfo("Success", "File saved successfully with original length preserved.")
        except Exception as e:
            messagebox.showerror("Parsing Error", f"Could not parse hex values: {str(e)}")

if __name__ == "__main__":
    app = HexEditorApp()
    app.mainloop()
