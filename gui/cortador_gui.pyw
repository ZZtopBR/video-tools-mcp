"""
Reel Cutter GUI
Loads a JSON cut list and executes all cuts with FFmpeg.
Usage: python cortador_gui.pyw
"""

import os, sys, json, subprocess, threading, shutil, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# ============================================================
# CONSTANTS — adjust to your environment
# ============================================================
VIDEOS_DIR = Path.home() / "Videos"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def ts_to_seconds(ts):
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def fmt_duration(secs):
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


# ============================================================
# APP
# ============================================================
class CortadorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Reel Cutter")
        self.root.geometry("780x560")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.cuts_data = None
        self.video_path = None
        self.running = False
        self.cancel_flag = False

        self._build_ui()

    def _build_ui(self):
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="Load JSON", command=self._load_json).pack(side="left", padx=(0, 10))
        self.btn_start = ttk.Button(toolbar, text="Start Cuts", command=self._start, state="disabled")
        self.btn_start.pack(side="left", padx=(0, 5))
        self.btn_cancel = ttk.Button(toolbar, text="Cancel", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left")

        self.video_label = ttk.Label(toolbar, text="No JSON loaded", font=("Segoe UI", 9))
        self.video_label.pack(side="right")

        list_frame = ttk.LabelFrame(self.root, text="Cuts", padding=5)
        list_frame.pack(fill="both", expand=True, padx=8, pady=(4, 2))

        cols = ("status", "name", "range", "duration", "tag", "description")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=10)
        self.tree.heading("status", text="")
        self.tree.heading("name", text="Reel")
        self.tree.heading("range", text="Range")
        self.tree.heading("duration", text="Dur.")
        self.tree.heading("tag", text="Tag")
        self.tree.heading("description", text="Description")
        self.tree.column("status", width=30, anchor="center")
        self.tree.column("name", width=200)
        self.tree.column("range", width=120, anchor="center")
        self.tree.column("duration", width=50, anchor="center")
        self.tree.column("tag", width=40, anchor="center")
        self.tree.column("description", width=280)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        prog_frame = ttk.Frame(self.root, padding=8)
        prog_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="Waiting...")
        ttk.Label(prog_frame, textvariable=self.status_var, font=("Segoe UI", 10)).pack(anchor="w")
        pbar_frame = ttk.Frame(prog_frame)
        pbar_frame.pack(fill="x", pady=(4, 0))
        self.progress = ttk.Progressbar(pbar_frame, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pct_var = tk.StringVar(value="")
        ttk.Label(pbar_frame, textvariable=self.pct_var, width=12).pack(side="right")

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.log_text = tk.Text(log_frame, height=6, font=("Consolas", 9), state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        if self.running:
            self.cancel_flag = True
        self.root.destroy()
        os._exit(0)

    def _load_json(self):
        path = filedialog.askopenfilename(
            title="Select cut-list JSON",
            initialdir=str(VIDEOS_DIR),
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if path:
            self._load_from_path(Path(path))

    def _load_from_path(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.cuts_data = data
            self.video_path = Path(data["video_path"])

            for item in self.tree.get_children():
                self.tree.delete(item)

            for i, cut in enumerate(data["cuts"]):
                start_s = ts_to_seconds(cut["start"])
                end_s = ts_to_seconds(cut["end"])
                dur = fmt_duration(end_s - start_s)
                rng = f"{cut['start']} > {cut['end']}"
                self.tree.insert("", "end", iid=str(i),
                                 values=("\u2b1c", cut["name"], rng, dur,
                                         cut.get("eixo", "-"), cut.get("desc", "")))

            self.video_label.config(text=self.video_path.name)
            self.btn_start.config(state="normal")
            self.status_var.set(f"{len(data['cuts'])} cuts loaded")
            self._log(f"JSON loaded: {path.name} ({len(data['cuts'])} cuts)")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON:\n{e}")

    def _cancel(self):
        self.cancel_flag = True
        self._log("Cancellation requested...")

    def _start(self):
        if not self.video_path or not self.video_path.exists():
            messagebox.showerror("Error", f"Video not found:\n{self.video_path}")
            return

        self.running = True
        self.cancel_flag = False
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        threading.Thread(target=self._process_cuts, daemon=True).start()

    def _process_cuts(self):
        cuts = self.cuts_data["cuts"]
        total = len(cuts)
        out_dir = self.video_path.parent / self.video_path.stem
        out_dir.mkdir(exist_ok=True)
        self._log(f"Output folder: {out_dir.name}/")

        done = 0
        errors = 0

        for i, cut in enumerate(cuts):
            if self.cancel_flag:
                self._log("Cancelled by user.")
                break

            name = cut["name"]
            start = cut["start"]
            end = cut["end"]
            start_s = ts_to_seconds(start)
            end_s = ts_to_seconds(end)
            duration = end_s - start_s

            self.root.after(0, self._set_status, i, "\ud83d\udd04")
            pct = (i / total) * 100
            self.root.after(0, self._update_progress, pct, f"Cutting {i+1}/{total}: {name}")
            self._log(f"[{i+1}/{total}] {name} ({start}>{end}, {fmt_duration(duration)})")

            out_path = out_dir / f"{name}.mp4"
            cmd = [
                FFMPEG, "-y",
                "-ss", start,
                "-i", str(self.video_path),
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                str(out_path)
            ]

            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if r.returncode == 0 and out_path.exists():
                    size_mb = out_path.stat().st_size / (1024 * 1024)
                    self.root.after(0, self._set_status, i, "\u2705")
                    self._log(f"  OK - {size_mb:.1f} MB")
                    done += 1
                else:
                    self.root.after(0, self._set_status, i, "\u274c")
                    self._log(f"  ERROR: {r.stderr[-200:]}")
                    errors += 1
            except subprocess.TimeoutExpired:
                self.root.after(0, self._set_status, i, "\u274c")
                self._log(f"  TIMEOUT (>5min)")
                errors += 1
            except Exception as e:
                self.root.after(0, self._set_status, i, "\u274c")
                self._log(f"  ERROR: {e}")
                errors += 1

        self.running = False
        self.root.after(0, lambda: self.btn_start.config(state="normal"))
        self.root.after(0, lambda: self.btn_cancel.config(state="disabled"))
        final = f"Done! {done} OK, {errors} errors" if not self.cancel_flag else "Cancelled"
        self.root.after(0, self._update_progress, 100, final)
        self._log(f"=== {final} ===")

    def _set_status(self, idx, icon):
        try:
            vals = list(self.tree.item(str(idx), "values"))
            vals[0] = icon
            self.tree.item(str(idx), values=vals)
        except Exception:
            pass

    def _update_progress(self, pct, text):
        self.progress["value"] = min(pct, 100)
        self.pct_var.set(f"{pct:.0f}%")
        self.status_var.set(text)


if __name__ == "__main__":
    root = tk.Tk()
    app = CortadorApp(root)
    root.mainloop()
