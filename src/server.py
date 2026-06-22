"""
Video Tools MCP Server
Transcription (Whisper) + Cutting (FFmpeg) + File management.

Usage: python server.py (stdio transport for Claude Desktop/Code)

Environment variables:
  VT_VIDEOS_DIR  - Working directory for videos (default: ~/videos)
  FFMPEG_PATH    - Path to ffmpeg binary (default: ffmpeg)
  FFPROBE_PATH   - Path to ffprobe binary (default: ffprobe)
  VT_PREFIX      - Prefix for renamed files (default: VT)
"""

import os, json, asyncio, subprocess, re, tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

VIDEOS_DIR = Path(os.environ.get("VT_VIDEOS_DIR", str(Path.home() / "videos")))
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_PATH", "ffprobe")
PREFIX = os.environ.get("VT_PREFIX", "VT")
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mts", ".3gp"}

mcp = FastMCP("video_tools_mcp")

def _s2ts(s): h=int(s//3600); m=int((s%3600)//60); return f"{h:02d}:{m:02d}:{int(s%60):02d}"
def _ts2s(ts):
    p=ts.split(":"); return int(p[0])*3600+int(p[1])*60+float(p[2]) if len(p)==3 else int(p[0])*60+float(p[1]) if len(p)==2 else float(p[0])

def _probe(path):
    r=subprocess.run([FFPROBE,"-v","quiet","-show_entries","format=duration,size:stream=width,height,codec_name,r_frame_rate","-select_streams","v:0","-of","json",path],capture_output=True,text=True,timeout=30)
    if r.returncode!=0: raise RuntimeError(f"ffprobe failed: {r.stderr[:300]}")
    return json.loads(r.stdout)

def _slug(t):
    t=t.lower().strip()
    for r,cs in {"a":"aáàãâä","e":"eéèêë","i":"iíìîï","o":"oóòõôö","u":"uúùûü","c":"cç","n":"nñ"}.items():
        for c in cs[1:]: t=t.replace(c,r)
    return re.sub(r'[^a-z0-9]+','_',t).strip('_')[:50]


class TranscribeIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    video_path:str=Field(...,description="Full path to the video file")
    model_size:str=Field(default="base",description="Whisper model: base|small|medium|large")
    language:str=Field(default="pt",description="Audio language code")

@mcp.tool(name="vt_transcribe")
async def vt_transcribe(params:TranscribeIn)->str:
    """Transcribe a video using Whisper and save a timestamped .md file."""
    vp=Path(params.video_path)
    if not vp.exists(): return json.dumps({"status":"error","msg":f"Not found: {vp}"})
    if vp.suffix.lower() not in VIDEO_EXT: return json.dumps({"status":"error","msg":f"Unsupported: {vp.suffix}"})
    try: import whisper
    except ImportError: return json.dumps({"status":"error","msg":"pip install openai-whisper"})

    try:
        m=_probe(str(vp)); dur=float(m["format"]["duration"]); sz=int(m["format"]["size"])/(1024*1024)
        st=m.get("streams",[{}])[0]; w,h=st.get("width","?"),st.get("height","?")
    except: dur=0;sz=vp.stat().st_size/(1024*1024);w=h="?"

    tmp=Path(tempfile.gettempdir())/f"wh_{os.getpid()}.wav"
    try:
        r=await asyncio.to_thread(subprocess.run,[FFMPEG,"-y","-i",str(vp),"-vn","-acodec","pcm_s16le","-ar","16000","-ac","1",str(tmp)],capture_output=True,text=True,timeout=120)
        if r.returncode!=0: return json.dumps({"status":"error","msg":f"Audio extract failed: {r.stderr[:300]}"})
    except Exception as e: return json.dumps({"status":"error","msg":str(e)})

    try:
        model=whisper.load_model(params.model_size)
        res=await asyncio.to_thread(model.transcribe,str(tmp),language=params.language,word_timestamps=False,verbose=False)
    except Exception as e: return json.dumps({"status":"error","msg":str(e)})
    finally:
        try:tmp.unlink(missing_ok=True)
        except:pass

    lines=[f"# Transcript: {vp.name}","",f"Duration: {_s2ts(dur)} | Resolution: {w}x{h} | Size: {sz:.1f}MB | Model: {params.model_size}","","---",""]
    for s in res["segments"]: lines.append(f"[{_s2ts(s['start'])} > {_s2ts(s['end'])}] {s['text'].strip()}"); lines.append("")
    md="\\n".join(lines); mdp=vp.with_suffix(".md"); mdp.write_text(md,encoding="utf-8")
    return json.dumps({"status":"ok","transcript_path":str(mdp),"duration":_s2ts(dur),"segments":len(res["segments"]),"transcript":md},ensure_ascii=False,indent=2)


class RenameIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    video_path:str=Field(...); tipo:str=Field(...,description="INTERVIEW|PODCAST|TESTIMONIAL|SPEECH|EVENT")
    tema:str=Field(...,description="Topic slug"); data:Optional[str]=Field(default=None,description="YYYYMMDD")

@mcp.tool(name="vt_rename")
async def vt_rename(params:RenameIn)->str:
    """Rename video+transcript following {PREFIX}_{TYPE}_{DATE}_{TOPIC} convention."""
    vp=Path(params.video_path)
    if not vp.exists(): return json.dumps({"status":"error","msg":"Not found"})
    VIDEOS_DIR.mkdir(parents=True,exist_ok=True)
    d=params.data or datetime.now().strftime("%Y%m%d")
    nn=f"{PREFIX}_{params.tipo.upper()}_{d}_{_slug(params.tema)}"; ext=vp.suffix
    nv=VIDEOS_DIR/f"{nn}{ext}"
    if nv.exists(): return json.dumps({"status":"error","msg":f"Exists: {nv.name}"})
    old=vp.name; vp.rename(nv)
    om=vp.with_suffix(".md"); nm=VIDEOS_DIR/f"{nn}.md"; mm=False
    if om.exists():
        c=om.read_text(encoding="utf-8").replace(f"# Transcript: {old}",f"# Transcript: {nn}{ext}")
        om.rename(nm); nm.write_text(c,encoding="utf-8"); mm=True
    return json.dumps({"status":"ok","old":old,"new":f"{nn}{ext}","path":str(nv),"md":str(nm) if mm else None},ensure_ascii=False,indent=2)


class CutIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    video_path:str=Field(...); start_time:str=Field(...,description="HH:MM:SS")
    end_time:str=Field(...,description="HH:MM:SS"); output_name:str=Field(...,description="Output name without extension")
    reencode:bool=Field(default=True)

@mcp.tool(name="vt_cut_reel")
async def vt_cut_reel(params:CutIn)->str:
    """Cut a segment from a video using FFmpeg. Saves to a cuts subfolder."""
    vp=Path(params.video_path)
    if not vp.exists(): return json.dumps({"status":"error","msg":"Not found"})
    cd=vp.parent/vp.stem; cd.mkdir(exist_ok=True)
    sn=re.sub(r'[^\\w\\-]','_',params.output_name); op=cd/f"{sn}{vp.suffix}"
    dur=_ts2s(params.end_time)-_ts2s(params.start_time)
    if dur<=0: return json.dumps({"status":"error","msg":"end must be after start"})
    if params.reencode:
        cmd=[FFMPEG,"-y","-ss",params.start_time,"-i",str(vp),"-t",str(dur),"-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-b:a","128k",str(op)]
    else:
        cmd=[FFMPEG,"-y","-ss",params.start_time,"-i",str(vp),"-to",str(dur),"-c","copy","-avoid_negative_ts","make_zero",str(op)]
    try:
        r=await asyncio.to_thread(subprocess.run,cmd,capture_output=True,text=True,timeout=300)
        if r.returncode!=0: return json.dumps({"status":"error","msg":r.stderr[:500]})
    except subprocess.TimeoutExpired: return json.dumps({"status":"error","msg":"Timeout >5min"})
    sz=op.stat().st_size/(1024*1024) if op.exists() else 0
    return json.dumps({"status":"ok","output":str(op),"start":params.start_time,"end":params.end_time,"duration":_s2ts(dur),"size_mb":round(sz,2)},ensure_ascii=False,indent=2)


class InfoIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    video_path:str=Field(...)

@mcp.tool(name="vt_info")
async def vt_info(params:InfoIn)->str:
    """Get video metadata: duration, resolution, codec, size, fps."""
    vp=Path(params.video_path)
    if not vp.exists(): return json.dumps({"status":"error","msg":"Not found"})
    try:
        m=_probe(str(vp)); dur=float(m["format"]["duration"]); sz=int(m["format"]["size"])/(1024*1024)
        s=m.get("streams",[{}])[0]; fps=s.get("r_frame_rate","?")
        if "/" in str(fps): p=fps.split("/"); fps=round(int(p[0])/int(p[1]),2)
        cd=vp.parent/vp.stem; cc=len([f for f in cd.iterdir() if f.suffix.lower() in VIDEO_EXT]) if cd.is_dir() else 0
        return json.dumps({"status":"ok","file":vp.name,"duration":_s2ts(dur),"resolution":f"{s.get('width','?')}x{s.get('height','?')}","codec":s.get("codec_name","?"),"fps":fps,"size_mb":round(sz,2),"has_transcript":vp.with_suffix(".md").exists(),"cuts":cc},ensure_ascii=False,indent=2)
    except Exception as e: return json.dumps({"status":"error","msg":str(e)})


class ListIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    folder:Optional[str]=Field(default=None,description="Folder to list. Default: VT_VIDEOS_DIR")

@mcp.tool(name="vt_list")
async def vt_list(params:ListIn)->str:
    """List all videos in the working directory with transcript and cut status."""
    d=Path(params.folder) if params.folder else VIDEOS_DIR; d.mkdir(parents=True,exist_ok=True)
    vids=[]
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXT:
            try:
                sz=f.stat().st_size/(1024*1024); cd=d/f.stem
                cc=len([c for c in cd.iterdir() if c.suffix.lower() in VIDEO_EXT]) if cd.is_dir() else 0
                vids.append({"name":f.name,"size_mb":round(sz,2),"transcript":f.with_suffix(".md").exists(),"cuts":cc,"path":str(f)})
            except: vids.append({"name":f.name,"error":"read failed"})
    return json.dumps({"status":"ok","folder":str(d),"total":len(vids),"videos":vids},ensure_ascii=False,indent=2)


if __name__=="__main__": mcp.run()
