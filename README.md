# Ableton for AI

<!-- mcp-name: io.github.peterkolbe/ableton-for-ai -->

> [!IMPORTANT]
> **For AI Agents:** Please read [AGENTS.md](./AGENTS.md) for detailed technical context and protocol specifications before working on this
> project.

**Ableton for AI** is the bridge between your DAW and AI models. It makes Ableton projects **hearable and visible** to AI models by
implementing the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) and exporting detailed project data.

## How

This repository provides two main ways to collaborate with AI:

### 1. 🤖 MCP Server (Real-time Interaction)

Connect Ableton Live directly to MCP-capable AI clients (like Claude Desktop, Cursor, or Cline). The AI can inspect, analyze, and even modify your project in real-time.

**Included Tools:**

* `get_overview`: **SESSION DISCOVERY**. Provides tempo, locators, and a list of all tracks with their current mixer state (volume, panning, etc.).
* `get_track`: **TRACK INSPECTION**. Comprehensive data for a single track: metadata, complete device chain, and all device parameters (with UI-readable strings).
* `get_tracks`: **BULK TRACK INSPECTION**. Query full data for a range of tracks in a single parallelized call.
* `analyze_stems`: **DEEP AUDIO ANALYSIS**. Triggers generation of audio summaries (.summary.json) and spectrograms (.spectrogram.webp) for all tracks.
* `set_track_volume` / `set_track_panning`: **MIXER CONTROL**. Remotely adjust track faders and panning.
* `set_device_parameter`: **REMOTE CONTROL**. Precisely adjust any parameter of any device in the project.

**Included Resources:**

* `ableton://stems/{track_name}/summary`: **AUDIO SUMMARY**. Compact analysis (JSON) containing LUFS, Peak, RMS, 10ms-frames, detected transients, and a `legend` field.
* `ableton://stems/{track_name}/spectrogram`: **VISUAL ANALYSIS**. Log-frequency spectrogram image (WebP) for visual frequency inspection.
* `ableton://stems/available/summaries`: Discovery resource for all tracks with available audio summaries.
* `ableton://stems/available/spectrograms`: Discovery resource for all tracks with available spectrograms.

### 2. 📂 CLI: Analyze & Upload (No MCP required)

This method is ideal for LLMs that don't support MCP directly (like ChatGPT or the Claude Web Interface).

* **What it does:**
  * Scans your `STEMS_SOURCE_DIR` for audio files matching your tracks.
  * Runs a parallelized analysis pipeline: LUFS (momentary/short-term), Peak, RMS, stereo correlation.
  * Generates optimized **spectrograms** (WebP) for each stem.
* **Workflow:** Run the analysis via CLI, then upload the output files (spectrograms + JSON) to any chatbot for mixing feedback.

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
- **Windows:** `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

### 3. Clone & Setup

Clone this repository and sync the dependencies:

```bash
git clone https://github.com/peterkolbe/ableton-for-ai.git
cd ableton-for-ai
uv sync
```

<details>
<summary>Alternative: pip (without uv)</summary>

```bash
git clone https://github.com/peterkolbe/ableton-for-ai.git
cd ableton-for-ai
pip install -e .
```

Then use `python` instead of `uv run` for all commands below.
</details>

### 4. Configure `config.py`

Open `config.py` and set the following values:

```python
# REQUIRED: Set this to the folder where your exported audio stems are located.
DEFAULT_STEMS_SOURCE_DIR = "/absolute/path/to/your/stems"

# Set this to match the format of your exported stems (default: "wav").
# Change to "mp3" if your stems are in MP3 format.
DEFAULT_PREFERRED_AUDIO_FORMAT = "wav"  # wav | mp3
```

> [!NOTE]
> Without a valid `DEFAULT_STEMS_SOURCE_DIR`, the audio analysis tools (`analyze_stems`) will not find any files to process.

---

## 🚀 Usage


### 1. MCP Server (Real-time Interaction)

#### Connect to an MCP Client

To use Ableton Live with an MCP-capable client (like Claude Desktop, Cursor, or Cline), add the server to your configuration.

##### Option A: Via PyPI (Recommended — no cloning required)

```bash
pip install ableton-for-ai
```

Then add to your MCP client config:

```json
{
  "mcpServers": {
    "ableton-for-ai": {
      "command": "uvx",
      "args": ["ableton-for-ai"],
      "env": {
        "STEMS_SOURCE_DIR": "/path/to/your/stems"
      }
    }
  }
}
```

##### Option B: From source (after cloning)

```json
{
  "mcpServers": {
    "ableton-for-ai": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/ableton-for-ai",
        "run",
        "mcp_server_ableton.py"
      ],
      "env": {
        "STEMS_SOURCE_DIR": "/path/to/your/stems"
      }
    }
  }
}
```

##### Where to put this config

- **Claude Desktop (macOS):** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Desktop (Windows):** `%APPDATA%\Claude\claude_desktop_config.json`
- **Cursor / Cline:** See their respective MCP documentation.

**Restart your MCP client** after saving the config.


#### Use the MCP Server within your Chatbot

Once connected, you can ask the AI about your project state. The AI will use the included tools and resources to fetch data directly from Ableton. For
example:

- "What is the current tempo and how many tracks do I have?"
- "Check the EQ settings on my Lead Synth track."
- "Show me an overview of the mixer state."
- "Analyze the stems and tell me if there are any frequency clashes."
- "Show me the spectrogram for the 'Kick' track."

### 2. CLI: Analyze & Upload (No MCP required)

Use this if you want to work with any AI by manually uploading project data and audio analysis.

#### Available CLI Commands

Full audio analysis (summaries + spectrograms + full analysis JSONs):

```bash
ableton-for-ai-cli analyze_stems
```

Extract Ableton project metadata only (tracks, devices, parameters):

```bash
ableton-for-ai-cli extract_ableton_project_data
```

Full pipeline (audio analysis AND project data extraction):

```bash
ableton-for-ai-cli analyze_stems_and_extract_ableton_project_data
```

<details>
<summary>Alternative: run from source (without installing)</summary>

```bash
uv run ableton_client.py analyze_stems
uv run ableton_client.py extract_ableton_project_data
uv run ableton_client.py analyze_stems_and_extract_ableton_project_data
```
</details>

> [!NOTE]
> The OSC daemon starts automatically — no need to launch it manually.

The results will be stored in the `./out` directory, organized into subfolders:

* `./out/project/`: Contains the Ableton project JSON file.
* `./out/summaries/`: Contains compressed audio analysis JSONs (optimized for AI).
* `./out/spectrograms/`: Contains spectrogram WebP images for each stem.
* `./out/analyses/`: Contains full high-resolution analysis JSONs.

#### Mixing with AI (Manual Example)

1. Drag and drop the files from your `out` folder into the chatbot. This typically includes audio stems, spectrograms (
   `.webp`), and analysis files (`.json`).
2. Use a prompt like this:

```markdown
I have attached several audio analysis files (spectrograms and energy analysis).
The given files only reflect a part of the project timeline, see below in Part.

Genre: Drum and Bass
Goal: Improve the clarity of the lead synth and make sure it doesn't clash with the vocals.
Part: The *.analysis.json and *.spectrogram.webp ONLY reflect the part starting at beat 113.

Please analyze the attached files and provide concrete mixing advice.
```

---

## ⚙️ Configuration

You can customize the server behavior by editing `config.py` or setting environment variables.

| Variable                  | Default Value                   | Description                                             |
|:--------------------------|:--------------------------------|:--------------------------------------------------------|
| `LOG_LEVEL`               | `"INFO"`                        | Logging verbosity (`INFO` or `DEBUG`).                  |
| `BASE_OUT_DIR`            | `"out"`                         | Directory for project data and analysis results.       |
| `STEMS_SOURCE_DIR`        | `"./stems"`                     | Path where exported stems are located.                  |
| `PREFERRED_AUDIO_FORMAT`  | `"mp3"`                         | Audio format to analyze (`mp3` or `wav`).               |
| `SPECTROGRAM_QUALITY`     | `90`                            | Quality of WebP spectrograms (1-100).                   |
| `RELEVANT_DEVICE_CLASSES` | `{"Eq8", "Compressor", ...}`    | List of Ableton device classes to include in extraction. |
| `RELEVANT_DEVICE_NAMES`   | `{"Pro-Q 4"}`                   | List of specific plugin names to include.               |

---

## 🔌 Using Custom VSTs / Plugins


### 1. Register the Plugin Name

In `config.py`, add the exact name of the plugin as it appears in Ableton to `RELEVANT_DEVICE_NAMES`.

### 2. Auto-Populate Parameters (The `Options.txt` Trick)

By default, Ableton Live only exposes the parameters of a third-party plugin, if the overall **parameter number
threshold** (_PluginAutoPopulateThreshold) is **below 64** (
default), [see here](https://help.ableton.com/hc/en-us/articles/6003224107292-Options-txt-file).
You can change this to 128 and hope that your favorite custom VSTs will be exposed. If they are still not exposed, because there are too
many (e.g. Fab Filter Pro Q 4),
you have to configure the parameters within ableton.

Force Ableton to automatically expose parameters by adding `-_PluginAutoPopulateThreshold=128` to your `Options.txt`:

- **Mac:** `~/Library/Preferences/Ableton/Live [Version]/Options.txt`
- **Windows:** `%AppData%\Ableton\Live [Version]\Preferences\Options.txt`

#### Mac Terminal Commands

To quickly set this up on a Mac, you can use these commands (replace `[Version]` with your actual Live version, e.g., `12.3.6`):

```bash
# 1. Navigate to the Preferences folder
cd ~/Library/Preferences/Ableton/Live\ 12.3.6/

# 2. Create the Options.txt file (if it doesn't exist)
touch Options.txt

# 3. Append the setting to the end of the file
echo "-_PluginAutoPopulateThreshold=128" >> Options.txt
```

OR open the file in a text editor and add the setting manually, e.g.

```bash
idea ~/Library/Preferences/Ableton/Live\ 12.3.6/Options.txt
```

---

## 🛠️ Development & Contributing

### MCP Inspector (Debugging)

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is useful for testing and debugging the MCP server during development.

Start it directly via terminal:

```bash
npx -y @modelcontextprotocol/inspector uv '--directory /absolute/path/to/ableton-for-ai run mcp_server_ableton.py'
```

Or start the Inspector without presets and configure it manually:

```bash
npx -y @modelcontextprotocol/inspector
```

Then enter the following in the Inspector UI:

- **Command:** `uv`
- **Arguments:** `--directory /absolute/path/to/ableton-for-ai run mcp_server_ableton.py`

### Linting & Formatting

```bash
uv run ruff check .
uv run ruff format .
```

---

## ⚠️ Known Limitations & Troubleshooting

### Automation Tracking

* **Not Supported:** Automation data is **not included** in the exports.
* **Technical Reason:** The underlying `AbletonOSC` script does not reliably expose automation status or points in its current version.

---

## 📄 License

This project is licensed under the MIT License.


---
