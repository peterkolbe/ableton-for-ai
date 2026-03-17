import asyncio
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from ableton_client import AbletonClient, log_info

# Initialize the MCP server
mcp = FastMCP("Ableton Live Controller", dependencies=["python-osc"])

# Create Ableton client
ableton_client = AbletonClient()


# ----- MCP TOOLS -----

@mcp.tool()
async def get_track_names(index_min: Optional[int] = None, index_max: Optional[int] = None) -> dict:
  """
  Holt die Namen aller Spuren (oder einer Range) in Ableton Live.
  Bevorzuge 'get_song_overview' für eine komplette Liste inklusive Tempo und Song-Länge.
  """
  return await ableton_client.get_track_names(index_min, index_max)


@mcp.tool()
async def get_song_overview() -> dict:
  """
  Liefert die wichtigsten globalen Session-Daten (Tempo, Spurenliste, etc.).
  NUTZE DIESES TOOL für den ersten Projektüberblick, anstatt jede Spur einzeln abzufragen.
  """
  return await ableton_client.get_song_overview()


@mcp.tool()
async def get_track_overview(track_index: int) -> dict:
  """
  Liefert Mix-relevante Basisdaten eines EINZELNEN Tracks (Volume, Panning, Solo, etc.).
  WICHTIG: Wenn du Daten für viele Tracks benötigst, nutze 'get_tracks_bulk' oder 'snapshot_mix_and_save_as_json' anstatt dieses Tool in einer Schleife aufzurufen.
  """
  return await ableton_client.get_track_overview(track_index)


@mcp.tool()
async def get_track_devices(track_index: int) -> dict:
  """
  Liefert alle Devices eines EINZELNEN Tracks effizient via Bulk-Abfrage.
  """
  return await ableton_client.get_track_devices(track_index)


@mcp.tool()
async def get_device_parameters(track_index: int, device_index: int) -> dict:
  """
  Liefert alle Parameter eines Devices effizient via Bulk-Abfrage.
  """
  return await ableton_client.get_device_parameters(track_index, device_index)


@mcp.tool()
async def get_all_mix_relevant_devices() -> dict:
  """
  Projektweite Suche: Findet alle mix-relevanten Devices effizient via Bulk-Abfragen.
  """
  return await ableton_client.get_all_mix_relevant_devices()


# TODO As this function currently refers to local files and also writes to local filesystem, it is not yet to be published as mcp tool
#   in the future, this should be fixed by accessing required files from cloud storage and writing results to cloud storage as well
# @mcp.tool()
# async def snapshot_mix_and_save_as_json() -> dict:
#   """
#   ULTIMATIVES MIX-TOOL: Erzeugt einen kompletten Snapshot des Mix-Zustands UND analysiert Audio-Stems parallel.
#   Optimiert für maximale Parallelität und Performance.
#   """
#   return await ableton_client.snapshot_mix_and_save_as_json()


@mcp.tool()
async def get_tracks_bulk(index_min: int, index_max: int, properties: List[str]) -> dict:
  """
  Effiziente Massenabfrage von Spureigenschaften.
  Nutzt optimierte Plural-Endpunkte wo vorhanden, sonst echte Parallelabfragen.
  """
  return await ableton_client.get_tracks_bulk(index_min, index_max, properties)


# ----- CLI RUNNER -----

if __name__ == "__main__":
  try:
    log_info("Starting Ableton Live MCP server...")
    mcp.run()
  finally:
    asyncio.run(ableton_client.close())
