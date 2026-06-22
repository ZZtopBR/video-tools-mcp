# Video Tools MCP

An MCP server that gives Claude the ability to process videos: transcribe with Whisper, cut reels with FFmpeg, and manage video files.

## Tools

| Tool | Description |
|------|-------------|
| `vt_transcribe` | Transcribe video audio using OpenAI Whisper, saves timestamped `.md` |
| `vt_cut_reel` | Cut a segment from a video using FFmpeg (fast seek + re-encode or stream copy) |
| `vt_rename` | Rename video + transcript following a configurable naming convention |
| `vt_info` | Get video metadata (duration, resolution, codec, fps, size) |
| `vt_list` | List all videos in the working directory with transcript/cut status |

## Prerequisites

- **Python 3.10+**
- **FFmpeg** installed and on PATH (or set `FFMPEG_PATH` env var)
- **Claude Desktop** or **Claude Code**

## Quick Start

```bash
git clone https://github.com/ZZtopBR/video-tools-mcp.git
cd video-tools-mcp
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VT_VIDEOS_DIR` | `~/videos` | Working directory for videos |
| `FFMPEG_PATH` | `ffmpeg` | Path to ffmpeg binary |
| `FFPROBE_PATH` | `ffprobe` | Path to ffprobe binary |
| `VT_PREFIX` | `VT` | Prefix for renamed files |

## Connect to Claude Desktop

```json
{
  "mcpServers": {
    "video-tools": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/video-tools-mcp/src/server.py"],
      "env": {
        "VT_VIDEOS_DIR": "/path/to/your/videos",
        "FFMPEG_PATH": "ffmpeg"
      }
    }
  }
}
```

## Workflow

1. **Transcribe** — `vt_transcribe` generates a timestamped `.md` alongside the video
2. **Analyze** — Claude reads the transcript, identifies key segments
3. **Cut** — `vt_cut_reel` extracts each segment as a separate file
4. **Organize** — `vt_rename` applies consistent naming conventions

## License

MIT

*Built with [OpenAI Whisper](https://github.com/openai/whisper), [FFmpeg](https://ffmpeg.org), and [MCP](https://modelcontextprotocol.io) by Anthropic.*
