# AI Agents Guide for Ableton-for-AI

This document provides essential technical context for AI agents working on this project.

## Project Purpose
The goal is to provide a bridge between Ableton Live and AI-driven tools (like Mix-Engineers or LLMs) to enable automated mixing, analysis, and data extraction of music projects.

## Core Components

### 1. `osc_daemon.py` (The Bridge)
- **Role**: A persistent background service that converts JSON-RPC over TCP into OSC over UDP.
- **API Documentation**: Whenever an agent needs to access Ableton via the `osc_daemon`, they **MUST** first consult the [AbletonOSC README](https://github.com/ideoforms/AbletonOSC) to ensure they are using the correct OSC addresses and parameter specifications.
- **Ports**: 
  - Listens for JSON-RPC on `127.0.0.1:65432`.
  - Sends OSC to Ableton on `11000`.
  - Receives OSC from Ableton on `11001`.
- **Key Features**:
  - **Request/Response Matching**: Uses a `request_id` and tracks pending futures to handle the asynchronous nature of OSC.
  - **Wildcard Support**: Can handle OSC wildcard queries (e.g., `/live/track/get/*`) and correctly dispatch multiple responses.
  - **Tolerant Matching**: Handles slight data type mismatches (int vs float) that AbletonOSC sometimes returns.
  - **OSC Bundling**: Supports grouped OSC messages in a single UDP packet for atomic execution and high performance.

### 2. `ableton_client.py` (The Interface)
- **Role**: High-level Python API for interacting with the `osc_daemon`.
- **Key Operations**:
  - `get_tracks`: Uses the highly efficient `/live/song/get/track_data` protocol for mass metadata retrieval.
  - `extract_ableton_project_data`: Quick extraction of project metadata, tracks, and device parameters.
  - `get_available_stems` / `get_available_spectrograms`: List available analysis results from previous runs.
  - `analyze_stems`: Independent audio analysis pipeline (spectrograms + energy) without project data.
- `analyze_stems_and_extract_ableton_project_data`: The full pipeline that gathers project data AND triggers deep audio analysis. **Required to enable audio-related resources.**
  - `set_device_parameter` / `set_track_volume`: Remote control methods to modify the Live session.
- **Rate Limiting**: Uses an `asyncio.Semaphore` (limit: 50) to prevent overwhelming the Ableton Remote Script while allowing high parallelism for parameter retrieval.

### 3. `audio_processor.py` (The Analyst)
- **Role**: Heavy-duty audio analysis using `librosa`, `pyloudnorm`, and `matplotlib`.
- **Outputs**:
  - **JSON Analysis**: Per-frame band energy, RMS, Peak, LUFS (momentary/short-term), and stereo correlation.
  - **Spectrograms**: Log-frequency visual representations of audio files (WebP format, optimized for size).
- **Note**: This runs in separate threads (via `asyncio.to_thread`) to avoid blocking the event loop.

### 4. MCP Server & Resources (`mcp_server_ableton.py`)
- **Role**: Exposes the `AbletonClient` tools and analysis results as MCP (Model Context Protocol) tools and resources.
- **Data Access Strategy**:
  - **Read (Fast)**: Use **Tools** like `get_overview`, `get_tracks` and `get_track` to explore the project state incrementally. 
  - **Update (Slow)**: Use **Tools** like `analyze_stems` ONLY when you need to perform an action or trigger a fresh extraction from Ableton.
- **Key Tools**:
  - `get_overview`: **SESSION DISCOVERY**. Quick session summary with detailed track info (Action, fast).
  - `get_track`: **TRACK INSPECTION**. Deep-dive into a single track (metadata + devices + all parameters) (Action, fast).
  - `get_tracks`: **BULK TRACK INSPECTION**. Highly optimized bulk fetch of full track data for a range of tracks (Action, fast).
  - `analyze_stems`: **DEEP AUDIO ANALYSIS**. Independent audio analysis pipeline (Action, slow).
- **Resources**:
  - `ableton://stems/{track_name}/summary`: **AUDIO SUMMARY**. Track-specific COMPRESSED audio summary (JSON). Includes frames, transients, and a `legend` field for key definitions. 
    *Note: Large summaries are split into chunks. If 'total_chunks' > 1, follow the 'chunk_uris' in the first response or use `ableton://stems/{track_name}/summary/chunk/{id}`.*
  - `ableton://stems/{track_name}/spectrogram`: **VISUAL ANALYSIS**. Spectrogram image for visual analysis (WebP).
  - `ableton://stems/available/summaries`: List of tracks with available summary JSONs.
  - `ableton://stems/available/spectrograms`: List of tracks with available spectrogram WebP images.
- **Notifications**: The server notifies clients when relevant state changes occur.

### 5. Modifying the Mix (New)
Agents can now actively change parameters in the Ableton session.
- **Track Level**: Use `set_track_volume`, `set_track_panning`, `set_track_mute`, or `set_track_solo`.
- **Device Level**: Use `set_device_parameter` (single) or `set_device_parameters` (bulk values for all parameters of a device).
- **Units**: Device parameters now include a `value_string` field (e.g., "-12.0 dB", "1500 Hz") providing the UI-readable value. Use this for interpretation, but always send the normalized `value` (0.0-1.0) when setting parameters.
- **Safety**: Always perform a `get_track` or `get_overview` AFTER significant changes to verify the new state.

## Important Protocol Details

### The `/live/song/get/track_data` Bulk Request
Always prefer this for fetching basic track info. 
**Format**: `[track_min, track_max, "track.name", "track.mute", ...]`
**Constraint**: Some attributes like `volume` and `panning` are NOT direct Track attributes in Ableton's LOM (they belong to the MixerDevice) and thus **cannot** be fetched in bulk via this specific endpoint. They must be fetched via individual `/live/track/get/volume <id>` calls.

### Sidechain Detection
The project attempts to detect whether a device has an active external sidechain input enabled.
1. **Detection Logic**: The client scans the device parameters for keywords like "S/C On" (Native Ableton) or "External Side Chain" (e.g., FabFilter Pro-Q 4).
2. **Field**: Every device in the JSON output includes the boolean field `has_external_side_chain_activated`.
3. **Note**: Due to limitations in the Ableton Live Object Model (LOM) for VSTs and some native devices via OSC, the exact routing source (track name) and tap point (e.g., Post FX) are currently not reliable and have been removed to avoid "unknown_not_exposed" values. AI agents should assume that if `has_external_side_chain_activated` is `true`, the device is being triggered by an external source (usually a Kick or Percussion track).

### Known Limitations (CRITICAL)
1. **No Automation Support**: All logic regarding `is_automated` or `automation_points` has been **removed**. The standard `AbletonOSC` remote script does not provide reliable access to these properties. Do not try to re-implement them without verifying script support.
2. **Device Parameter Logic**: Fetching parameters for all devices is slow. The client filters for "mix-relevant" devices (EQ Eight, Compressor, etc.) in some tools, but the full extraction fetches everything.

## Development Guidelines
- **Linting**: Use `uv run ruff check .` and `uv run ruff format .`.
- **Dependency Management**: Managed via `uv` (`pyproject.toml` and `uv.lock`).
- **Logging**: Control verbosity via `LOG_LEVEL=DEBUG` environment variable.
- **Ports**: Ensure port 11000/11001 and 65432 are free.
- **Commit Messages**: Follow [Conventional Commits](https://www.conventionalcommits.org/). Format:
  ```
  <type>(<scope>): <short description>

  <optional body>
  ```
  **Types**: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `perf`, `ci`  
  **Scope** (optional): affected module, e.g. `mcp_server`, `osc_daemon`, `audio_processor`, `config`, `docs`  
  **Examples**:
  - `feat(mcp_server): add set_track_solo tool`
  - `fix(osc_daemon): handle timeout for wildcard responses`
  - `refactor(ableton_client): extract bulk parameter fetch into helper`
  - `docs: update README quick start section`
  - `chore(deps): bump fastmcp to 3.3.0`

## Testing Procedures
To ensure stability and correctness after making changes to `ableton_client.py` or `osc_daemon.py`, follow these steps:

1. **Restart Daemon (if modified)**: If you made changes to `osc_daemon.py`, you MUST restart it.
   ```bash
   pkill -f "python.*osc_daemon.py" || true
   nohup uv run osc_daemon.py > daemon.log 2>&1 &
   sleep 2
   ```
2. **Unit/Feature Test**: Directly test the specific function you modified. For example, if you changed a bulk retrieval method, run a small script to verify that specific call.
3. **Integration Test**: Always run a full project data extraction (via CLI) to verify the entire pipeline (Client -> Daemon -> Ableton -> Daemon -> Client).
   ```bash
   uv run ableton_client.py extract_ableton_project_data
   ```
4. **Validation**:
   - Check the logs (`daemon.log` and stdout) for any "Unknown OSC address" or "Timeout" errors.
   - Inspect the output file `out/project/ableton-project-for-ai.json` to ensure the data structure is correct and all expected fields are present.
   - Pay special attention to the `volume` and `panning` fields as they are fetched separately.

## Data Structures
The output is organized into the following directory structure within `out/`:
- `out/project/`: Contains `ableton-project-for-ai.json` (Project metadata, tracks, devices).
- `out/summaries/`: Contains `*.summary.json` files (Compressed analysis for AI consumption).
- `out/spectrograms/`: Contains `*.spectrogram.webp` files (Visualizations).
- `out/analyses/`: Contains `*.analysis.json` files (Full high-resolution analysis, not used by MCP).

### Project JSON
Found in `out/project/ableton-project-for-ai.json`. It contains:
- Global metadata (tempo, time signature).
- Track list with mixer settings.
- Device chains for each track.
- All parameters for each device (including `value`, `value_string`, `min`, `max`).
