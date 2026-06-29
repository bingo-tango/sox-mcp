"""
SoX MCP Server — audio inspection & processing tools for LLM agents.

Provides thin, structured wrappers around sox.exe and soxi.exe so that
agents can inspect audio metadata and perform common operations
(resample, remix channels, trim, convert format, apply effects, etc.).

Each tool returns JSON text the LLM can reliably parse.
"""

import re
import asyncio
import json
import os
import shutil
from datetime import timedelta, datetime
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _locate_exe(name: str) -> Optional[str]:
    """Search PATH for an executable (sync — safe at module-import time)."""
    # shutil.which works cross-platform and handles both "sox" and "sox.exe"
    return shutil.which(name)


def _resolve_sox() -> tuple[str, str]:
    """Return (sox_path, soxi_path), honouring SOX_PATH env-var override."""
    sox = os.environ.get("SOX_PATH") or _locate_exe("sox.exe") or _locate_exe("sox")
    if not sox:
        sox = "sox"  # fall back to PATH lookup at runtime
    # Derive soxi from sox by swapping the stem
    soxi = str(Path(sox).with_stem("soxi"))
    return sox, soxi


SOX, SOXI = _resolve_sox()

app = Server("sox-audio-tools")


def _check_file(path: str, mode: str = "r") -> Optional[str]:
    """Return an error string if the file is not accessible, else None."""
    p = Path(path)
    if mode == "w" and p.exists():
        return f"Output path already exists and would be overwritten: {path}"
    if mode == "r" and not p.exists():
        return f"File not found: {path}"
    return None


def _validate_io(inp: str, out: str) -> Optional[str]:
    """Check input exists and output doesn't. Return error or None."""
    e_in = _check_file(inp)
    if e_in:
        return e_in
    e_out = _check_file(out, "w")
    if e_out:
        return e_out
    return None


async def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return (-1, "", f"SoX timed out after {timeout}s")
    return (proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace"))


def _ok(text: str, **kwargs) -> list[TextContent]:
    """Wrap a success message (extra kwargs are json-encoded and appended)."""
    parts = [text]
    if kwargs:
        parts.append(json.dumps(kwargs, indent=2))
    return [TextContent(type="text", text="\n".join(parts))]


def _err(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"ERROR: {text}")]


def _fmt_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    return str(timedelta(seconds=round(seconds)))


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools():
    return [
        # -- Inspection -------------------------------------------------------
        Tool(
            name="audio_info",
            description="Get complete metadata for one or more audio files (duration, sample rate, channels, bitrate, format, encoding).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to a single audio file, or a JSON array of paths."
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: subset of fields to return. Values: type, sample_rate, channels, samples, duration, duration_seconds, bits_per_sample, bitrate, encoding, comments. Omit to return all."
                    }
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="list_files",
            description="List files in a directory. Useful for discovering audio files in a folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Path to the directory to list."
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: list of extensions to filter by (e.g. ['wav', 'mp3']).",
                    },
                },
                "required": ["directory_path"],
            },
        ),
        # -- Conversion -------------------------------------------------------
        Tool(
            name="convert_audio",
            description="Convert an audio file to a different format. Optionally resample or change bit depth in the same pass.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string", "description": "Source audio file path."},
                    "output_file": {"type": "string", "description": "Destination file path (include extension, e.g. output.mp3)."},
                    "sample_rate": {"type": "integer", "description": "Optional: resample to this rate (Hz)."},
                    "bits": {"type": "integer", "description": "Optional: bit depth (8, 16, 24, 32)."},
                    "channels": {"type": "integer", "description": "Optional: force channel count (1=mono, 2=stereo)."},
                    "compression": {"type": "number", "description": "Optional: compression factor for formats that support it (e.g. MP3 quality 0-1)."},
                },
                "required": ["input_file", "output_file"],
            },
        ),
        # -- Resample ---------------------------------------------------------
        Tool(
            name="resample",
            description="Change the sample rate of an audio file (e.g. 48000 -> 44100 Hz).",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string"},
                    "output_file": {"type": "string"},
                    "sample_rate": {"type": "integer", "description": "Target sample rate in Hz."},
                    "quality": {
                        "type": "string",
                        "enum": ["fast", "low", "medium", "high", "vhq"],
                        "description": "Resampling quality preset (default: medium).",
                    },
                },
                "required": ["input_file", "output_file", "sample_rate"],
            },
        ),
        # -- Channel operations -----------------------------------------------
        Tool(
            name="remix_channels",
            description="Remix/merge/split channels. E.g. stereo->mono, extract left channel, swap channels, or create custom mixes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string"},
                    "output_file": {"type": "string"},
                    "mapping": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Remix mapping strings. E.g. ['1'] = left only, ['2'] = right only, ['1,2'] = stereo pass-through, ['2,1'] = swap, ['1+2'] = both to mono (sum). See SoX 'remix' docs.",
                    },
                },
                "required": ["input_file", "output_file", "mapping"],
            },
        ),
        # -- Trim / Pad -------------------------------------------------------
        Tool(
            name="trim_audio",
            description="Trim an audio file to a time range, or silence-clip the start/end.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string"},
                    "output_file": {"type": "string"},
                    "start": {"type": "number", "description": "Start time in seconds (default: 0)."},
                    "duration": {"type": "number", "description": "Duration to keep in seconds. Omit to keep to end of file."},
                    "trim_silence_start": {
                        "type": "boolean",
                        "description": "If true, auto-detect and skip leading silence (VAD). Mutually exclusive with explicit start."
                    },
                    "trim_silence_end": {
                        "type": "boolean",
                        "description": "If true, trim trailing silence."
                    },
                },
                "required": ["input_file", "output_file"],
            },
        ),
        # -- Volume / Gain ----------------------------------------------------
        Tool(
            name="adjust_volume",
            description="Change volume, normalise peak, or adjust loudness of an audio file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string"},
                    "output_file": {"type": "string"},
                    "gain_db": {"type": "number", "description": "Gain adjustment in dB (e.g. +3, -6)."},
                    "normalize": {
                        "type": "boolean",
                        "description": "If true, normalise peak to 0 dBFS (ignores gain_db)."
                    },
                },
                "required": ["input_file", "output_file"],
            },
        ),
        # -- Concatenate / Merge ----------------------------------------------
        Tool(
            name="concatenate_audio",
            description="Concatenate (append) or mix/merge multiple audio files into one.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of input file paths.",
                    },
                    "output_file": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["concatenate", "merge", "mix"],
                        "description": "concatenate (default): append end-to-end. merge: sum corresponding channels. mix: like merge but normalised for channel count.",
                    },
                },
                "required": ["input_files", "output_file"],
            },
        ),
        # -- Effects ----------------------------------------------------------
        Tool(
            name="apply_effect",
            description="Apply a SoX effect (equalizer, reverb, bass, treble, fade, tempo, pitch, lowpass, highpass, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {"type": "string"},
                    "output_file": {"type": "string"},
                    "effect": {
                        "type": "string",
                        "description": "Effect name. Common: equalizer, bass, treble, reverb, echo, fade, tempo, pitch, lowpass, highpass, sinc, chorus, flanger, phaser, norm, stat, stats.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Effect-specific arguments as strings. E.g. for equalizer: ['5000', '2', '5']. For reverb: []. For fade: ['in', '3', 'out', '2'].",
                    },
                },
                "required": ["input_file", "output_file", "effect"],
            },
        ),
        # -- Stats / Analysis -------------------------------------------------
        Tool(
            name="audio_stats",
            description="Compute playback statistics (RMS, max, min, CRC, peak level, etc.) for one or more files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to audio file, or JSON array of paths."
                    },
                },
                "required": ["file_path"],
            },
        ),
        # -- Generate ---------------------------------------------------------
        Tool(
            name="generate_tone",
            description="Generate a pure sine tone, silence, or white noise file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "output_file": {"type": "string"},
                    "duration": {"type": "number", "description": "Duration in seconds."},
                    "frequency": {"type": "number", "description": "Frequency in Hz (for sine tone). Omit for silence/noise."},
                    "waveform": {
                        "type": "string",
                        "enum": ["sine", "square", "sawtooth", "triangle", "whitenoise", "pinknoise"],
                        "description": "Waveform type (default: sine).",
                    },
                    "sample_rate": {"type": "integer", "description": "Sample rate (default: 44100)."},
                },
                "required": ["output_file", "duration"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    router = {
        "audio_info": _handle_audio_info,
        "list_files": _handle_list_files,
        "convert_audio": _handle_convert,
        "resample": _handle_resample,
        "remix_channels": _handle_remix,
        "trim_audio": _handle_trim,
        "adjust_volume": _handle_volume,
        "concatenate_audio": _handle_concat,
        "apply_effect": _handle_effect,
        "audio_stats": _handle_stats,
        "generate_tone": _handle_generate,
    }
    handler = router.get(name)
    if not handler:
        return _err(f"Unknown tool: {name}")
    return await handler(arguments)


# -- audio_info -------------------------------------------------------------

async def _handle_list_files(args: dict):
    path_str = args["directory_path"]
    extensions = args.get("extensions", [])

    p = Path(path_str)
    if not p.is_dir():
        return _err(f"'{path_str}' is not a directory or does not exist.")

    files_found = []
    ext_set = {ext.lower().lstrip('.') for ext in extensions}

    try:
        for entry in p.iterdir():
            if entry.is_file():
                ext = entry.suffix.lower().lstrip('.')
                if not extensions or ext in ext_set:
                    stats = entry.stat()
                    mtime = datetime.fromtimestamp(stats.st_mtime).isoformat()
                    files_found.append({
                        "name": entry.name,
                        "size_bytes": stats.st_size,
                        "extension": ext,
                        "last_modified": mtime
                    })
    except Exception as e:
        return _err(f"Error reading directory: {str(e)}")

    return _ok(f"Found {len(files_found)} files in {path_str}.", files=files_found)


async def _handle_audio_info(args: dict):
    raw = args["file_path"]
    # Accept either a string path or a JSON-encoded array
    if isinstance(raw, str):
        files = json.loads(raw) if raw.strip().startswith("[") else [raw]
    else:
        files = raw

    results = []
    for fp in files:
        if (e := _check_file(fp)):
            results.append({"file": fp, "error": e})
            continue

        # Call soxi -V to get detailed metadata
        proc = await asyncio.create_subprocess_exec(
            SOXI, "-V", fp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            results.append({"file": fp, "error": stderr.decode(errors="replace").strip()})
            continue

        output = stdout.decode(errors="replace")
        info = {"file": fp}

        # Parsing logic for soxi -V output
        # Example lines:
        # Channels       : 1
        # Sample Rate    : 48000
        # Precision      : 16-bit
        # Duration       : 00:14:59.66 = 43183908 samples ~ 67474.9 CDDA sectors
        # Sample Encoding: 16-bit FLAC

        # Regex patterns
        patterns = {
            "channels": r"Channels\s*:\s*(\d+)",
            "sample_rate": r"Sample Rate\s*:\s*(\d+)",
            "bit_depth": r"Precision\s*:\s*(\d+)-bit",
            "duration_text": r"Duration\s*:\s*([^=]+)",
            "samples": r"=\s*(\d+)\s*samples",
            "format": r"Sample Encoding\s*:\s*(.*)",
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                val = match.group(1).strip()
                if key == "channels" or key == "sample_rate" or key == "samples":
                    try:
                        info[key] = int(val)
                    except ValueError:
                        info[key] = val
                elif key == "bit_depth":
                    try:
                        info[key] = int(val)
                    except ValueError:
                        info[key] = val
                else:
                    info[key] = val

        # Handle duration as seconds if possible
        if "duration_text" in info:
            dur_str = info.pop("duration_text")
            # Try to parse the H:MM:SS.ss part
            try:
                # Duration is usually '00:14:59.66'
                time_part = dur_str.split('=')[0].strip()
                # Simple way to convert H:M:S to seconds
                parts = time_part.split(':')
                if len(parts) == 3:
                    h, m, s = parts
                    total_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    info["duration_seconds"] = total_seconds
                info["duration"] = time_part
            except Exception:
                info["duration"] = dur_str

        results.append(info)

    return _ok(f"Retrieved metadata for {len(results)} file(s).", metadata=results)


# -- convert_audio ----------------------------------------------------------

async def _handle_convert(args: dict):
    inp = args["input_file"]
    out = args["output_file"]

    if (e := _validate_io(inp, out)):
        return _err(e)

    cmd = [SOX, inp, out]

    if "sample_rate" in args:
        cmd.extend(["-r", str(args["sample_rate"])])
    if "bits" in args:
        cmd.extend(["-b", str(args["bits"])])
    if "channels" in args:
        cmd.extend(["-c", str(args["channels"])])
    if "compression" in args:
        cmd.extend(["-C", str(args["compression"])])

    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Converted {inp} -> {out}")


# -- resample ---------------------------------------------------------------

async def _handle_resample(args: dict):
    inp = args["input_file"]
    out = args["output_file"]
    sr = args["sample_rate"]

    if (e := _validate_io(inp, out)):
        return _err(e)

    quality = args.get("quality", "medium")
    cmd = [SOX, inp, out, "rate", "-v", quality, str(sr)]

    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Resampled {inp} -> {out} at {sr} Hz (quality={quality})")


# -- remix_channels ---------------------------------------------------------

async def _handle_remix(args: dict):
    inp = args["input_file"]
    out = args["output_file"]
    mapping = args["mapping"]

    if (e := _validate_io(inp, out)):
        return _err(e)

    remix_args = ",".join(mapping)
    cmd = [SOX, inp, out, "remix", remix_args]

    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Remixed {inp} -> {out} with mapping [{remix_args}]")


# -- trim_audio -------------------------------------------------------------

async def _handle_trim(args: dict):
    inp = args["input_file"]
    out = args["output_file"]

    if (e := _validate_io(inp, out)):
        return _err(e)

    effects: list[str] = []

    if args.get("trim_silence_start"):
        # VAD: trim leading silence (1% threshold, 0.1s frames)
        effects.extend(["silence", "1", "0.1%"])
    elif "start" in args:
        start = args["start"]
        if args.get("duration"):
            effects.extend(["trim", str(start), str(args["duration"])])
        else:
            effects.extend(["trim", str(start)])

    if args.get("trim_silence_end"):
        effects.extend(["silence", "1", "0.1%"])

    if not effects:
        return _err("Provide at least one of: start, duration, trim_silence_start, trim_silence_end")

    cmd = [SOX, inp, out, *effects]
    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Trimmed {inp} -> {out}")


# -- adjust_volume ----------------------------------------------------------

async def _handle_volume(args: dict):
    inp = args["input_file"]
    out = args["output_file"]

    if (e := _validate_io(inp, out)):
        return _err(e)

    effects: list[str] = []

    if args.get("normalize"):
        effects.append("norm")
    elif "gain_db" in args:
        gain = args["gain_db"]
        # SoX vol effect accepts dB suffix directly
        effects.extend(["vol", f"{gain}dB"])
    else:
        return _err("Provide gain_db or normalize=true")

    cmd = [SOX, inp, out, *effects]
    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Volume adjusted {inp} -> {out}")


# -- concatenate_audio ------------------------------------------------------

async def _handle_concat(args: dict):
    files = args["input_files"]
    out = args["output_file"]
    mode = args.get("mode", "concatenate")

    for fp in files:
        if (e := _check_file(fp)):
            return _err(e)
    if (e := _check_file(out, "w")):
        return _err(e)

    # sox --combine <mode> for long form; short flags -m / -M are self-contained
    if mode == "concatenate":
        combine_flag = ["--combine", "concatenate"]
    elif mode == "merge":
        combine_flag = ["-M"]
    else:  # mix
        combine_flag = ["-m"]

    cmd = [SOX, *combine_flag, *files, out]
    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"{mode.title()}d {len(files)} file(s) -> {out}")


# -- apply_effect -----------------------------------------------------------

async def _handle_effect(args: dict):
    inp = args["input_file"]
    out = args["output_file"]
    effect = args["effect"]
    options = args.get("options", [])

    if (e := _validate_io(inp, out)):
        return _err(e)

    cmd = [SOX, inp, out, effect, *options]
    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Applied {effect} {inp} -> {out}")


# -- audio_stats ------------------------------------------------------------

async def _handle_stats(args: dict):
    raw = args["file_path"]
    if isinstance(raw, str):
        files = json.loads(raw) if raw.strip().startswith("[") else [raw]
    else:
        files = raw

    results = []
    for fp in files:
        if (e := _check_file(fp)):
            results.append({"file": fp, "error": e})
            continue
        cmd = [SOX, fp, "-n", "stats", "-1"]
        rc, out_text, err = await _run(cmd)
        if rc != 0:
            results.append({"file": fp, "error": err.strip()})
            continue
        # Parse stats output into a structured dict
        stats = {"file": fp}
        for line in out_text.strip().splitlines():
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().lower().replace(" ", "_")
                v = v.strip()
                try:
                    v = float(v)
                except ValueError:
                    pass
                stats[k] = v
        results.append(stats)

    return _ok(f"Statistics for {len(results)} file(s).", stats=results)


# -- generate_tone ----------------------------------------------------------

async def _handle_generate(args: dict):
    out = args["output_file"]
    dur = args["duration"]
    freq = args.get("frequency")
    wf = args.get("waveform", "sine")
    sr = args.get("sample_rate", 44100)

    if (e := _check_file(out, "w")):
        return _err(e)

    cmd = [SOX, "-n", "-r", str(sr), out, "synth", str(dur)]

    if freq is not None:
        cmd.extend([wf, str(freq)])
    else:
        cmd.append(wf)

    rc, _, err = await _run(cmd)
    if rc != 0:
        return _err(f"SoX returned {rc}: {err.strip()}")
    return _ok(f"Generated {wf} ({dur}s, {sr}Hz) -> {out}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as streams:
        init_options = app.create_initialization_options()
        await app.run(streams[0], streams[1], init_options)


if __name__ == "__main__":
    asyncio.run(main())
