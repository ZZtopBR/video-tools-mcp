"""
Video Transcriber GUI
Extracts audio (FFmpeg) + transcribes (Whisper) + saves .md with timestamps.
Usage: python transcriber_gui.pyw
"""

import os, sys, json, subprocess, threading, time, tempfile, traceback, shutil, tkinter as tk

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

# ============================================================
# CONSTANTS — adjust to your environment
# ============================================================
VIDEOS_DIR = Path.home() / "Videos"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mts", ".3gp"}

MODEL_SPEED = {"base": 10, "small": 6, "medium": 3, "large": 1}


def seconds_to_ts(s):
    return f"{int(s//3600):02d}:{int((s%3600)//60):02d}:{int(s%60):02d}"


def get_duration(path):
    cmd = [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
           "-of", "json", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0


def get_metadata(path):
    cmd = [FFPROBE, "-v", "quiet",
           "-show_entries", "format=duration,size:stream=width,height,codec_name,r_frame_rate",
           "-select_streams", "v:0", "-of", "json", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return json.loads(r.stdout)
    except Exception:
        return {}


class TranscriberApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Transcriber")
        self.root.geometry("720x620")
        self.root.resizable(True, True)

        self.queue = []
        self.running = False
        self.cancel_flag = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.running:
            self.cancel_flag = True
        self.root.destroy()
        os._exit(0)

    def _build_ui(self):
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="+ Add Videos", command=self._add_videos).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=(0, 15))

        ttk.Label(toolbar, text="Model:").pack(side="left")
        self.model_var = tk.StringVar(value="base")
        ttk.Combobox(toolbar, textvariable=self.model_var, values=["base", "small", "medium", "large"],
                     state="readonly", width=8).pack(side="left", padx=(3, 15))

        self.btn_start = ttk.Button(toolbar, text="Start Queue", command=self._start_queue)
        self.btn_start.pack(side="left", padx=(0, 5))
        self.btn_cancel = ttk.Button(toolbar, text="Cancel", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left")

        queue_frame = ttk.LabelFrame(self.root, text="Video Queue", padding=5)
        queue_frame.pack(fill="both", expand=True, padx=8, pady=(4, 2))

        cols = ("status", "file", "duration", "size")
        self.tree = ttk.Treeview(queue_frame, columns=cols, show="headings", height=8)
        self.tree.heading("status", text="")
        self.tree.heading("file", text="File")
        self.tree.heading("duration", text="Duration")
        self.tree.heading("size", text="Size")
        self.tree.column("status", width=40, anchor="center")
        self.tree.column("file", width=360)
        self.tree.column("duration", width=80, anchor="center")
        self.tree.column("size", width=90, anchor="center")

        scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        prog_frame = ttk.Frame(self.root, padding=8)
        prog_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="Waiting...")
        ttk.Label(prog_frame, textvariable=self.status_var, font=("Segoe UI", 10)).pack(anchor="w")

        prog_bar_frame = ttk.Frame(prog_frame)
        prog_bar_frame.pack(fill="x", pady=(4, 0))
        self.progress = ttk.Progressbar(prog_bar_frame, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pct_var = tk.StringVar(value="0%")
        ttk.Label(prog_bar_frame, textvariable=self.pct_var, width=18).pack(side="right")

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.log_text = tk.Text(log_frame, height=8, font=("Consolas", 9), state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _add_videos(self):
        files = filedialog.askopenfilenames(
            title="Select videos",
            initialdir=str(VIDEOS_DIR) if VIDEOS_DIR.exists() else None,
            filetypes=[("Videos", " ".join(f"*{e}" for e in VIDEO_EXT)), ("All", "*.*")]
        )
        for f in files:
            p = Path(f)
            if p.suffix.lower() not in VIDEO_EXT:
                continue
            if any(item["path"] == str(p) for item in self.queue):
                continue
            dur = get_duration(p)
            size_mb = p.stat().st_size / (1024 * 1024)
            self.queue.append({"path": str(p), "duration": dur, "status": "pending"})
            self.tree.insert("", "end", iid=str(p),
                             values=("\u2b1c", p.name, seconds_to_ts(dur), f"{size_mb:.0f} MB"))

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.queue = [q for q in self.queue if q["path"] != iid]
            self.tree.delete(iid)

    def _cancel(self):
        self.cancel_flag = True
        self._log("Cancellation requested...")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_progress(self, pct, status_text=None):
        pct = min(max(pct, 0), 100)
        self.progress["value"] = pct
        self.pct_var.set(f"{pct:.0f}%")
        if status_text:
            self.status_var.set(status_text)

    def _set_item_status(self, path, icon):
        try:
            vals = list(self.tree.item(path, "values"))
            vals[0] = icon
            self.tree.item(path, values=vals)
        except Exception:
            pass

    def _start_queue(self):
        pending = [q for q in self.queue if q["status"] == "pending"]
        if not pending:
            messagebox.showinfo("Empty queue", "Add videos first.")
            return
        self.running = True
        self.cancel_flag = False
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        pending = [q for q in self.queue if q["status"] == "pending"]
        for idx, item in enumerate(pending):
            if self.cancel_flag:
                self._log("Queue cancelled.")
                break
            path = item["path"]
            name = Path(path).name
            self.root.after(0, self._set_item_status, path, "\ud83d\udd04")
            self._log(f"--- Processing ({idx+1}/{len(pending)}): {name} ---")
            try:
                self._transcribe_one(item)
                item["status"] = "done"
                self.root.after(0, self._set_item_status, path, "\u2705")
                self._log(f"Done: {name}")
            except Exception as e:
                item["status"] = "error"
                self.root.after(0, self._set_item_status, path, "\u274c")
                self._log(f"ERROR in {name}: {e}")

        self.running = False
        self.root.after(0, lambda: self.btn_start.configure(state="normal"))
        self.root.after(0, lambda: self.btn_cancel.configure(state="disabled"))
        self.root.after(0, self._update_progress, 100, "Queue done!" if not self.cancel_flag else "Cancelled.")
        self._log("=== Queue finished ===")

    def _transcribe_one(self, item):
        video_path = Path(item["path"])
        duration = item["duration"]
        model_name = self.model_var.get()

        self.root.after(0, self._update_progress, 0, f"Extracting audio: {video_path.name}")
        self._log(f"Extracting audio (WAV 16kHz mono)...")

        audio_tmp = Path(tempfile.gettempdir()) / f"whisper_{os.getpid()}.wav"

        cmd = [FFMPEG, "-y", "-i", str(video_path),
               "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
               str(audio_tmp)]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {proc.stderr[-200:]}")

        audio_size = audio_tmp.stat().st_size / (1024 * 1024)
        self._log(f"Audio extracted: {audio_size:.1f} MB in {time.time() - t0:.1f}s")

        if self.cancel_flag:
            audio_tmp.unlink(missing_ok=True)
            return

        speed = MODEL_SPEED.get(model_name, 10)
        estimated_secs = (duration / speed) if duration > 0 else 120
        self._log(f"Starting Whisper (model: {model_name}, est: {estimated_secs:.0f}s)...")
        self.root.after(0, self._update_progress, 10, f"Transcribing: {video_path.name}")

        t_start = time.time()
        progress_stop = threading.Event()

        def progress_monitor():
            while not progress_stop.is_set():
                elapsed = time.time() - t_start
                pct = min(10 + (elapsed / estimated_secs) * 85, 95)
                status = f"Transcribing... {elapsed:.0f}s / ~{estimated_secs:.0f}s est."
                self.root.after(0, self._update_progress, pct, status)
                progress_stop.wait(2)

        monitor = threading.Thread(target=progress_monitor, daemon=True)
        monitor.start()

        try:
            import whisper
            import wave
            import numpy as np
            with wave.open(str(audio_tmp), 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            model = whisper.load_model(model_name)
            result = model.transcribe(audio_np, language="pt", verbose=False)
        finally:
            progress_stop.set()
            monitor.join(timeout=3)
            audio_tmp.unlink(missing_ok=True)

        elapsed_total = time.time() - t_start
        self._log(f"Transcription done in {elapsed_total:.1f}s ({len(result['segments'])} segments)")

        self.root.after(0, self._update_progress, 96, f"Saving transcript...")

        meta = get_metadata(str(video_path))
        dur_str = seconds_to_ts(duration)
        size_mb = video_path.stat().st_size / (1024 * 1024)
        stream = meta.get("streams", [{}])[0] if meta.get("streams") else {}
        width = stream.get("width", "?")
        height = stream.get("height", "?")

        md_lines = [
            f"# Transcript: {video_path.name}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| **File** | `{video_path.name}` |",
            f"| **Duration** | {dur_str} |",
            f"| **Resolution** | {width}x{height} |",
            f"| **Size** | {size_mb:.1f} MB |",
            f"| **Transcribed** | {datetime.now().strftime('%Y-%m-%d %H:%M')} |",
            f"| **Whisper model** | {model_name} |",
            f"| **Language** | pt |",
            "",
            "---",
            "",
            "## Full Transcript",
            "",
        ]

        for seg in result["segments"]:
            start = seconds_to_ts(seg["start"])
            end = seconds_to_ts(seg["end"])
            text = seg["text"].strip()
            md_lines.append(f"[{start} > {end}] {text}")
            md_lines.append("")

        md_path = video_path.with_suffix(".md")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        self.root.after(0, self._update_progress, 100, f"Saved: {md_path.name}")
        self._log(f"Transcript saved: {md_path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = TranscriberApp(root)
    root.mainloop()
