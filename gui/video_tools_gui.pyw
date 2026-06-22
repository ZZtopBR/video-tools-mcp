"""
Video Tools — Unified App
Transcription (Whisper) + Reel Cutting (FFmpeg) in one window.
Sequential queue with per-item progress.
"""
import os, sys, json, subprocess, threading, time, traceback, shutil, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')

# ============================================================
# CONSTANTS — adjust to your environment
# ============================================================
VIDEOS_DIR = Path.home() / "Videos"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mts", ".3gp"}
MODEL_SPEED = {"base": 10, "small": 6, "medium": 3, "large": 1}

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

def s2ts(s, precise=False):
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    if precise: return f"{h:02d}:{m:02d}:{sec:04.1f}"
    return f"{h:02d}:{m:02d}:{int(sec):02d}"

def ts2s(ts):
    p = ts.split(":")
    if len(p)==3: return int(p[0])*3600+int(p[1])*60+float(p[2])
    if len(p)==2: return int(p[0])*60+float(p[1])
    return float(p[0])

def fmtdur(s): m, s = divmod(int(s), 60); return f"{m}:{s:02d}"

def get_dur(path):
    try:
        r = subprocess.run([FFPROBE,"-v","quiet","-show_entries","format=duration","-of","json",str(path)],
                           capture_output=True, text=True, timeout=15)
        return float(json.loads(r.stdout)["format"]["duration"])
    except: return 0

def get_meta(path):
    try:
        r = subprocess.run([FFPROBE,"-v","quiet","-show_entries",
            "format=duration,size:stream=width,height,codec_name","-select_streams","v:0","-of","json",str(path)],
            capture_output=True, text=True, timeout=15)
        return json.loads(r.stdout)
    except: return {}


class VideoToolsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Tools")
        self.root.geometry("820x660")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.cancel_flag = False
        self.running = False

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb = nb

        self._build_transcription(nb)
        self._build_cuts(nb)

    def _on_close(self):
        self.cancel_flag = True
        self.root.destroy()
        os._exit(0)

    # ========================================================
    # TAB 1 — TRANSCRIPTION
    # ========================================================
    def _build_transcription(self, nb):
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text="  Transcription  ")

        tb = ttk.Frame(tab); tb.pack(fill="x", pady=(0,5))
        ttk.Button(tb, text="+ Add Videos", command=self._tr_add).pack(side="left", padx=(0,5))
        ttk.Button(tb, text="Remove", command=self._tr_rem).pack(side="left", padx=(0,15))
        ttk.Label(tb, text="Model:").pack(side="left")
        self.tr_model = tk.StringVar(value="base")
        ttk.Combobox(tb, textvariable=self.tr_model, values=["base","small","medium","large"],
                     state="readonly", width=8).pack(side="left", padx=(3,15))
        self.tr_btn = ttk.Button(tb, text="Start Queue", command=self._tr_start)
        self.tr_btn.pack(side="left", padx=(0,5))
        ttk.Button(tb, text="Cancel", command=self._cancel).pack(side="left")

        qf = ttk.LabelFrame(tab, text="Video Queue", padding=4)
        qf.pack(fill="both", expand=True, pady=(0,4))
        cols = ("st","file","duration","size","progress")
        self.tr_tree = ttk.Treeview(qf, columns=cols, show="headings", height=7)
        self.tr_tree.heading("st", text=""); self.tr_tree.column("st", width=30, anchor="center")
        self.tr_tree.heading("file", text="File"); self.tr_tree.column("file", width=340)
        self.tr_tree.heading("duration", text="Duration"); self.tr_tree.column("duration", width=70, anchor="center")
        self.tr_tree.heading("size", text="Size"); self.tr_tree.column("size", width=80, anchor="center")
        self.tr_tree.heading("progress", text="Progress"); self.tr_tree.column("progress", width=120, anchor="center")
        sb = ttk.Scrollbar(qf, orient="vertical", command=self.tr_tree.yview)
        self.tr_tree.configure(yscrollcommand=sb.set)
        self.tr_tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.tr_queue = []

        lf = ttk.LabelFrame(tab, text="Log", padding=4); lf.pack(fill="both", expand=True)
        self.tr_log = tk.Text(lf, height=6, font=("Consolas",9), state="disabled", wrap="word")
        ls = ttk.Scrollbar(lf, orient="vertical", command=self.tr_log.yview)
        self.tr_log.configure(yscrollcommand=ls.set)
        self.tr_log.pack(side="left", fill="both", expand=True); ls.pack(side="right", fill="y")

    def _tr_add(self):
        files = filedialog.askopenfilenames(title="Select videos", initialdir=str(VIDEOS_DIR),
            filetypes=[("Videos"," ".join(f"*{e}" for e in VIDEO_EXT)),("All","*.*")])
        for f in files:
            p = Path(f)
            if p.suffix.lower() not in VIDEO_EXT: continue
            if any(q["path"]==str(p) for q in self.tr_queue): continue
            dur = get_dur(p); size = p.stat().st_size/(1024*1024)
            self.tr_queue.append({"path":str(p),"duration":dur,"status":"pending"})
            self.tr_tree.insert("","end",iid=str(p),
                values=("\u2b1c", p.name, s2ts(dur), f"{size:.0f} MB", "\u2014"))

    def _tr_rem(self):
        for iid in self.tr_tree.selection():
            self.tr_queue = [q for q in self.tr_queue if q["path"]!=iid]
            self.tr_tree.delete(iid)

    def _tr_start(self):
        if self.running: messagebox.showinfo("Wait","A process is already running."); return
        pending = [q for q in self.tr_queue if q["status"]=="pending"]
        if not pending: messagebox.showinfo("Empty","Add videos first."); return
        self.running = True; self.cancel_flag = False
        self.tr_btn.config(state="disabled")
        threading.Thread(target=self._tr_run, daemon=True).start()

    def _tr_run(self):
        pending = [q for q in self.tr_queue if q["status"]=="pending"]
        for idx, item in enumerate(pending):
            if self.cancel_flag: break
            p = item["path"]; name = Path(p).name
            self._tset(self.tr_tree, p, 0, "\ud83d\udd04"); self._tprog(self.tr_tree, p, "Extracting audio...")
            self._log(self.tr_log, f"[{idx+1}/{len(pending)}] {name}")
            try:
                self._tr_one(item)
                item["status"] = "done"
                self._tset(self.tr_tree, p, 0, "\u2705"); self._tprog(self.tr_tree, p, "Done")
            except Exception as e:
                item["status"] = "error"
                self._tset(self.tr_tree, p, 0, "\u274c"); self._tprog(self.tr_tree, p, "ERROR")
                self._log(self.tr_log, f"  ERROR: {e}")
        self.running = False
        self.root.after(0, lambda: self.tr_btn.config(state="normal"))
        self._log(self.tr_log, "=== Queue finished ===")

    def _tr_one(self, item):
        vp = Path(item["path"]); dur = item["duration"]; model = self.tr_model.get()

        self._log(self.tr_log, "  Extracting audio WAV 16kHz...")
        import tempfile
        atmp = Path(tempfile.gettempdir()) / f"whisper_{os.getpid()}.wav"
        r = subprocess.run([FFMPEG,"-y","-i",str(vp),"-vn","-acodec","pcm_s16le",
                            "-ar","16000","-ac","1",str(atmp)], capture_output=True, text=True, timeout=300)
        if r.returncode != 0: raise RuntimeError(f"FFmpeg: {r.stderr[-200:]}")
        self._tprog(self.tr_tree, str(vp), "Audio OK. Whisper...")
        self._log(self.tr_log, f"  Audio: {atmp.stat().st_size/(1024*1024):.1f} MB")
        if self.cancel_flag: atmp.unlink(missing_ok=True); return

        speed = MODEL_SPEED.get(model, 10); est = dur/speed if dur>0 else 120
        self._log(self.tr_log, f"  Whisper ({model}), ~{est:.0f}s est...")
        t0 = time.time(); stop = threading.Event()

        def mon():
            while not stop.is_set():
                el = time.time()-t0; pct = min(int(el/est*100), 95)
                self.root.after(0, self._tprog, self.tr_tree, str(vp), f"Transcribing {pct}% ({int(el)}s)")
                stop.wait(3)
        mt = threading.Thread(target=mon, daemon=True); mt.start()

        try:
            import whisper, wave, numpy as np
            with wave.open(str(atmp),'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)/32768.0
            m = whisper.load_model(model)
            result = m.transcribe(audio, language="pt", verbose=False, word_timestamps=True)
        finally:
            stop.set(); mt.join(timeout=3); atmp.unlink(missing_ok=True)

        self._log(self.tr_log, f"  {len(result['segments'])} segments in {time.time()-t0:.1f}s")

        meta = get_meta(str(vp)); st = (meta.get("streams",[{}])[0] if meta.get("streams") else {})
        w,h = st.get("width","?"), st.get("height","?")
        sz = vp.stat().st_size/(1024*1024)
        lines = [f"# Transcript: {vp.name}","",
            "| Field | Value |","|---|---|",
            f"| **File** | `{vp.name}` |", f"| **Duration** | {s2ts(dur)} |",
            f"| **Resolution** | {w}x{h} |", f"| **Size** | {sz:.1f} MB |",
            f"| **Transcribed** | {datetime.now().strftime('%Y-%m-%d %H:%M')} |",
            f"| **Whisper model** | {model} |", f"| **Language** | pt |",
            "","---","","## Full Transcript",""]
        for seg in result["segments"]:
            words = seg.get("words", [])
            if words:
                seg_start = words[0]["start"]; seg_end = words[-1]["end"]
            else:
                seg_start = seg["start"]; seg_end = seg["end"]
            lines.append(f"[{s2ts(seg_start, precise=True)} > {s2ts(seg_end, precise=True)}] {seg['text'].strip()}")
            lines.append("")
        vp.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
        self._tprog(self.tr_tree, str(vp), "Saved!")
        self._log(self.tr_log, f"  Saved: {vp.with_suffix('.md').name}")

    # ========================================================
    # TAB 2 — CUTS
    # ========================================================
    def _build_cuts(self, nb):
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text="  Cuts  ")

        tb = ttk.Frame(tab); tb.pack(fill="x", pady=(0,5))
        ttk.Button(tb, text="Load Instructions", command=self._ct_load).pack(side="left", padx=(0,5))
        ttk.Button(tb, text="Clear List", command=self._ct_clear).pack(side="left", padx=(0,15))
        self.ct_btn = ttk.Button(tb, text="Start Cuts", command=self._ct_start, state="disabled")
        self.ct_btn.pack(side="left", padx=(0,5))
        ttk.Button(tb, text="Cancel", command=self._cancel).pack(side="left")
        self.ct_info = ttk.Label(tb, text="", font=("Segoe UI",9))
        self.ct_info.pack(side="right")

        cf = ttk.LabelFrame(tab, text="Cut Plan (review before running)", padding=4)
        cf.pack(fill="both", expand=True, pady=(0,4))
        cols = ("st","reel","range","dur","tag","topic","video")
        self.ct_tree = ttk.Treeview(cf, columns=cols, show="headings", height=10)
        self.ct_tree.heading("st",text=""); self.ct_tree.column("st",width=30,anchor="center")
        self.ct_tree.heading("reel",text="Reel"); self.ct_tree.column("reel",width=200)
        self.ct_tree.heading("range",text="Range"); self.ct_tree.column("range",width=130,anchor="center")
        self.ct_tree.heading("dur",text="Dur."); self.ct_tree.column("dur",width=50,anchor="center")
        self.ct_tree.heading("tag",text="Tag"); self.ct_tree.column("tag",width=40,anchor="center")
        self.ct_tree.heading("topic",text="Topic"); self.ct_tree.column("topic",width=250)
        self.ct_tree.heading("video",text="Video"); self.ct_tree.column("video",width=150)
        sb = ttk.Scrollbar(cf, orient="vertical", command=self.ct_tree.yview)
        self.ct_tree.configure(yscrollcommand=sb.set)
        self.ct_tree.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self.ct_cuts = []

        lf = ttk.LabelFrame(tab, text="Log", padding=4); lf.pack(fill="both", expand=True)
        self.ct_log = tk.Text(lf, height=5, font=("Consolas",9), state="disabled", wrap="word")
        ls = ttk.Scrollbar(lf, orient="vertical", command=self.ct_log.yview)
        self.ct_log.configure(yscrollcommand=ls.set)
        self.ct_log.pack(side="left",fill="both",expand=True); ls.pack(side="right",fill="y")

    def _ct_load(self):
        files = filedialog.askopenfilenames(title="Load cut instructions",
            initialdir=str(VIDEOS_DIR),
            filetypes=[("Instruction JSON","*.instrucoes.json"),("JSON","*.json"),("All","*.*")])
        for f in files:
            self._ct_load_file(Path(f))

    def _ct_load_file(self, path):
        try:
            with open(path,"r",encoding="utf-8") as f: data = json.load(f)
            vp = data["video_path"]; vname = Path(vp).name
            for c in data["cuts"]:
                dur_s = ts2s(c["end"]) - ts2s(c["start"])
                iid = f"ct_{len(self.ct_cuts)}"
                entry = {
                    "video_path": vp, "reel_name": c["reel_name"],
                    "start": c["start"], "end": c["end"],
                    "eixo": c.get("eixo","-"), "tema": c.get("tema",""),
                    "status": "pending", "iid": iid
                }
                self.ct_cuts.append(entry)
                self.ct_tree.insert("","end",iid=iid,
                    values=("\u2b1c", c["reel_name"], f"{c['start']} > {c['end']}",
                            fmtdur(dur_s), c.get("eixo","-"), c.get("tema","")[:40], vname))
            self.ct_btn.config(state="normal")
            self.ct_info.config(text=f"{len(self.ct_cuts)} cuts total")
            self._log(self.ct_log, f"Loaded: {path.name} ({len(data['cuts'])} cuts from {vname})")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load:\n{e}")

    def _ct_clear(self):
        for item in self.ct_tree.get_children(): self.ct_tree.delete(item)
        self.ct_cuts.clear()
        self.ct_btn.config(state="disabled")
        self.ct_info.config(text="")

    def _ct_start(self):
        if self.running: messagebox.showinfo("Wait","A process is already running."); return
        pending = [c for c in self.ct_cuts if c["status"]=="pending"]
        if not pending: messagebox.showinfo("Empty","No pending cuts."); return
        self.running = True; self.cancel_flag = False
        self.ct_btn.config(state="disabled")
        threading.Thread(target=self._ct_run, daemon=True).start()

    def _ct_run(self):
        pending = [c for c in self.ct_cuts if c["status"]=="pending"]
        total = len(pending); done = errs = 0

        for idx, c in enumerate(pending):
            if self.cancel_flag: break
            iid = c["iid"]; name = c["reel_name"]
            vp = Path(c["video_path"])
            start = c["start"]; end = c["end"]
            dur = ts2s(end) - ts2s(start)

            self._tset(self.ct_tree, iid, 0, "\ud83d\udd04")
            self._log(self.ct_log, f"[{idx+1}/{total}] {name} ({start}>{end}, {fmtdur(dur)})")

            out_dir = vp.parent / vp.stem
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{name}.mp4"

            cmd = [FFMPEG, "-y", "-ss", start, "-i", str(vp),
                   "-t", str(dur), "-c:v","libx264","-preset","fast","-crf","18",
                   "-c:a","aac","-b:a","192k", str(out_path)]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if r.returncode == 0 and out_path.exists():
                    mb = out_path.stat().st_size/(1024*1024)
                    c["status"] = "done"; done += 1
                    self._tset(self.ct_tree, iid, 0, "\u2705")
                    self._log(self.ct_log, f"  OK - {mb:.1f} MB")
                else:
                    c["status"] = "error"; errs += 1
                    self._tset(self.ct_tree, iid, 0, "\u274c")
                    self._log(self.ct_log, f"  ERROR: {r.stderr[-200:]}")
            except Exception as e:
                c["status"] = "error"; errs += 1
                self._tset(self.ct_tree, iid, 0, "\u274c")
                self._log(self.ct_log, f"  ERROR: {e}")

        self.running = False
        self.root.after(0, lambda: self.ct_btn.config(state="normal"))
        msg = f"Done! {done} OK, {errs} errors" if not self.cancel_flag else "Cancelled"
        self._log(self.ct_log, f"=== {msg} ===")

    # ========================================================
    # SHARED
    # ========================================================
    def _cancel(self):
        self.cancel_flag = True

    def _log(self, widget, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        widget.configure(state="normal")
        widget.insert("end", f"[{ts}] {msg}\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _tset(self, tree, iid, col, val):
        try:
            vals = list(tree.item(iid, "values")); vals[col] = val
            self.root.after(0, lambda: tree.item(iid, values=vals))
        except: pass

    def _tprog(self, tree, iid, text):
        try:
            vals = list(tree.item(iid, "values")); vals[4] = text
            self.root.after(0, lambda: tree.item(iid, values=vals))
        except: pass


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoToolsApp(root)
    root.mainloop()
