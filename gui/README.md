# GUI Companions

Standalone Tkinter desktop apps that complement the MCP server tools.
Require **FFmpeg** on PATH and **OpenAI Whisper** (`pip install openai-whisper`) for transcription.

| App | Description |
|---|---|
| `video_tools_gui.pyw` | **Unified app** — Transcription + Reel Cutting in a tabbed interface |
| `transcriber_gui.pyw` | Standalone transcription queue (Whisper) |
| `cortador_gui.pyw` | Standalone reel cutter from a JSON cut-list |

## Quick Start

```bash
# Install dependencies
pip install openai-whisper numpy

# Run the unified app (or any individual GUI)
pythonw video_tools_gui.pyw
```

## Cut-list JSON format

```json
{
  "video_path": "C:/Videos/interview.mp4",
  "cuts": [
    {"name": "clip_01", "start": "00:01:30", "end": "00:02:15", "eixo": "A", "desc": "Opening remarks"},
    {"name": "clip_02", "start": "00:05:00", "end": "00:05:45", "eixo": "B", "desc": "Key insight"}
  ]
}
```

Output clips are saved to a subfolder named after the source video.
