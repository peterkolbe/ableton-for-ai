# Ableton for AI

**Ableton for AI** is the bridge between your DAW and AI models. It makes Ableton projects **hearable and visible** to AI models by implementing the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) and exporting detailed project snapshots.

## How

This repository provides two main ways to collaborate with AI:

### 1. 📂 Snapshot Mix & Manual Analysis
This method is ideal for all LLMs (like ChatGPT, Claude Web Interface), even if they don't support MCP directly.

* **Function:** `snapshot_mix_and_save_as_json` (in `ableton_client.py`)
* **What it does:**
    * Extracts all relevant project data (track names, volume, panning, devices, parameters) as JSON.
    * Copies audio stems to the `out` folder.
    * Generates **spectrograms** and performs **audio analysis** for each stem.
* **Workflow:** Generate the snapshot via CLI and simply upload the files (JSON + images + analysis) to your chatbot to receive informed feedback on your mix or arrangement.

### 2. 🤖 Ableton MCP Server (Real-time Interaction)
Connect Ableton Live directly to MCP-capable chatbots (like Claude Desktop or Cursor/Cline). The AI can "see" and analyze your project in real-time.

**Included Tools:**
* `get_song_overview`: The "master view". Provides tempo, song length, and a list of all tracks.
* `get_track_names`: Lists all track names.
* `get_track_overview`: Detailed info for a track (volume, panning, solo/mute, device list).
* `get_track_devices`: Lists all effects and instruments loaded on a track.
* `get_device_parameters`: Reads all parameters of a specific device (e.g., EQ settings, compressor threshold).
* `get_all_mix_relevant_devices`: Searches project-wide for important mixing tools (EQs, compressors).
* `get_tracks_bulk`: Efficient query of properties for multiple tracks simultaneously.

---

## ⚡ Quick Start

### 1. Install AbletonOSC
This project relies on **AbletonOSC** to communicate with Ableton Live.
- Download and install [AbletonOSC](https://github.com/ideoforms/AbletonOSC).
- Follow the instructions there to add it as a **Control Surface** in Ableton Live's Link/Tempo/MIDI settings.

### 2. Install `uv`
`uv` is an extremely fast Python package installer and resolver.
- **Homebrew:** `brew install uv`
- **Shell (macOS / Linux):** `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows:** `powershell -c "irmo https://astral.sh/uv/install.ps1 | iex"`

### 3. Clone & Setup
Clone this repository and sync the dependencies:
```bash
# git clone <this-repo-url>
cd ableton-for-ai
uv sync
```

---

## 🚀 Usage

### Prerequisite: Start the OSC Daemon
The daemon acts as the bridge between the MCP server and Ableton. It **must always be running** in the background for both workflows:
```bash
uv run osc_daemon.py
```

### 1. Snapshot Mix & Manual Analysis
Use this if you want to work with any AI by manually uploading project data and audio analysis.

#### Generate the Snapshot
Run this command to create a full mix snapshot:
```bash
uv run ableton_client.py snapshot_mix_and_save_as_json
```
The results (JSON + Spectrograms + Analysis) will be stored in the `./out` directory.

#### Mixing with AI (Manual Example)
1. Drag and drop the files from your `out` folder into the chatbot. This typically includes the JSON snapshot, audio stems, spectrograms (`.png`), and analysis files (`.json`).
2. Use a prompt like this:
```markdown
I have attached a JSON snapshot of my Ableton project and several audio analysis files (spectrograms and energy analysis).

Genre: Drum and Bass
Goal: Improve the clarity of the lead synth and make sure it doesn't clash with the vocals.

Please analyze the attached files and provide concrete mixing advice. 
Look at the frequency spectrum of the 'Drum' stem and the 'Bass' stem to identify potential conflicts.
```

### 2. Ableton MCP Server
Use this for real-time interaction with MCP-capable clients (like Claude Desktop or Cline).

#### Connect to an MCP Client
Add the server to your configuration:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Example Configuration:**
```json
{
  "mcpServers": {
    "ableton-live": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/ableton-live-mcp-server",
        "run",
        "mcp_server_ableton.py"
      ]
    }
  }
}
```

#### Mixing with AI (MCP Example)
Once connected, you can ask the AI about your project state. The AI will use the included tools to fetch data directly from Ableton. For example:
- "What is the current tempo and how many tracks do I have?"
- "Check the EQ settings on my Lead Synth track."
- "Are there any compressors on the Master bus?"
- "Find all tracks that have a Compressor device and show me their thresholds."

---

## ⚙️ Configuration
You can customize the server behavior by editing `config.py` or setting environment variables.

| Variable                  | Default Value                   | Description                                             |
|:--------------------------|:--------------------------------|:--------------------------------------------------------|
| `LOG_LEVEL`               | `"INFO"`                        | Logging verbosity (`INFO` or `DEBUG`).                  |
| `BASE_OUT_DIR`            | `"out"`                         | Directory for snapshots and analysis results.           |
| `STEMS_SOURCE_DIR`        | `"/Users/.../ai-stem-exchange"` | Path where exported stems are located.                  |
| `PREFERRED_AUDIO_FORMAT`  | `"mp3"`                         | Audio format to analyze (`mp3` or `wav`).               |
| `RELEVANT_DEVICE_CLASSES` | `{"Eq8", "Compressor", ...}`    | List of Ableton device classes to include in snapshots. |
| `RELEVANT_DEVICE_NAMES`   | `{"Pro-Q 4"}`                   | List of specific plugin names to include.               |

---

## 🔌 Using Custom VSTs / Plugins
By default, Ableton Live only exposes a few parameters for third-party plugins. To make these visible to the MCP server:

### 1. Register the Plugin Name
In `config.py`, add the exact name of the plugin as it appears in Ableton to `RELEVANT_DEVICE_NAMES`.

### 2. Auto-Populate Parameters (The `Options.txt` Trick)
Force Ableton to automatically expose parameters by adding `-_PluginAutoPopulateThreshold=128` to your `Options.txt`:
- **Mac:** `~/Library/Preferences/Ableton/Live [Version]/Options.txt`
- **Windows:** `%AppData%\Ableton\Live [Version]\Preferences\Options.txt`

---

## 📄 License
This project is licensed under the MIT License.
