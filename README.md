# SoX MCP Server

A Model Context Protocol (MCP) server that provides powerful audio inspection and processing capabilities to LLM agents. This server wraps the [SoX (Sound eXchange)](http://sox.sourceforge.net/) command-line utilities, allowing AI agents to "hear" and manipulate audio files through structured JSON interfaces.

## 🚀 Features

Agents can use this server to perform a wide range of audio tasks:

- **Inspection**: Get detailed metadata (duration, sample rate, channels, bitrate, format, encoding) and statistical analysis (RMS, peak level, etc.) from audio files.
- **Conversion**: Convert audio between formats (e.g. WAV to MP3).
- **Processing**: 
    - Resample audio to different sample rates.
    - Adjust volume, normalize peaks, or apply gain.
    - Trim audio or remove silence (VAD).
    - Remix or swap audio channels.
    - Concatenate or mix multiple audio files.
    - Apply a vast array of SoX effects (reverb, equalizer, delay, etc.).
- **Generation**: Generate pure sine tones, white noise, or silence for testing.
- **Discovery**: List audio files within a directory with optional extension filtering.

## 📋 Prerequisites

1.  **Python 3.10+**
2.  **SoX Utilities**: You must have the `sox` and `soxi` executables installed on your system and available in your `PATH`.
    - **Windows**: Download from [sox.sourceforge.net](http://sox.sourceforge.net/) or install via `choco install sox`.
    - **macOS**: `brew install sox`
    - **Linux**: `sudo apt-get install sox libsox-fmt-all`

## 🛠️ Installation

### 1. Clone the repository
```bash
git clone <repository-url>
cd sox-mcp-server
```

### 2. Set up a Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 💻 Development

### Running the Server
The server uses the MCP standard I/O transport. To run it manually for debugging:
```bash
python sox_mcp_server.py
```

### Testing
We provide a smoke test script to verify the server and its connection to the SoX binaries:
```bash
# Ensure you are in your virtual environment
python test_smoke.py
```

### Environment Variables
If `sox` or `soxi` are not in your system `PATH`, you can specify their location using the `SOX_PATH` environment variable.

---

## 🤖 Integration

### Claude Desktop
To use this server with the Claude Desktop app, add it to your configuration file.

**Config Location:**
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Configuration Example:**
```json
{
  "mcpServers": {
    "sox-mcp": {
      "command": "C:\\path\\to\\your\\project\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\your\\project\\sox_mcp_server.py"
      ],
      "env": {
        "SOX_PATH": "C:\\Program Files\\sox\\sox.exe"
      }
    }
  }
}
```
*Note: Use absolute paths for the python executable and the server script. If `sox` is not in your system `PATH`, use the `SOX_PATH` environment variable as shown above.*

### LM Studio
LM Studio supports MCP servers. To add this server:

1. Open **LM Studio**.
2. Navigate to the **MCP** section in the settings/sidebar.
3. Click **Add Server** (or equivalent depending on your version).
4. Select **Command/Stdio** as the connection type.
5. Enter the following:
   - **Command**: The path to your `.venv\Scripts\python.exe`.
   - **Arguments**: The absolute path to `sox_mcp_server.py`.
6. Click **Save/Connect**.

---

## 🛠️ Tool List

| Tool | Description |
| :--- | :--- |
| `audio_info` | Get complete metadata for one or more files. |
| `list_files` | List files in a directory with optional extension filtering. |
| `convert_audio` | Convert audio formats and change bit depth. |
| `resample` | Change the sample rate of an audio file. |
| `remix_channels` | Merge, split, or swap audio channels. |
| `trim_audio` | Trim time ranges or auto-trim silence. |
| `adjust_volume` | Normalize or adjust gain (dB). |
| `concatenate_audio` | Append, merge, or mix multiple files. |
| `apply_effect` | Apply any SoX effect (reverb, EQ, etc.). |
| `audio_stats` | Compute RMS, peak, and other playback statistics. |
| `generate_tone` | Generate test tones or noise files. |
