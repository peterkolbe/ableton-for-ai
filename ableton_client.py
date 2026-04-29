import asyncio
import json
import os
import re
import shutil
import sys
import time
from typing import List, Optional, Dict, Any

import config_utils as config
from audio_processor import process_audio_file


def log_info(message: str):
    """Prints info messages to stderr."""
    print(f"[INFO] {message}", file=sys.stderr, flush=True)


def log_debug(message: str):
    """Prints debug messages to stderr if LOG_LEVEL is DEBUG."""
    if config.LOG_LEVEL == "DEBUG":
        print(f"[DEBUG] {message}", file=sys.stderr, flush=True)


def log_error(message: str):
    """Prints error messages to stderr."""
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)


class AbletonClient:
    def __init__(self, host="127.0.0.1", port=65432):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False
        self.responses = {}  # Store futures keyed by (request_id)
        self.lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()  # Lock for socket write operations
        self.semaphore = asyncio.Semaphore(
            50
        )  # Increased from 10 to mask network latency for many small requests (value_string)
        self._request_id = 0
        self.response_task = None

    async def connect(self):
        """Connect to the OSC daemon via asyncio."""
        if not self.connected:
            try:
                self.reader, self.writer = await asyncio.open_connection(
                    self.host, self.port
                )
                self.connected = True
                self.response_task = asyncio.create_task(self.start_response_reader())
                return True
            except Exception as e:
                log_error(f"Failed to connect to daemon: {e}")
                return False
        return True

    async def start_response_reader(self):
        """Background task to read responses from the asyncio stream."""
        buffer = ""
        decoder = json.JSONDecoder()

        while self.connected:
            try:
                data = await self.reader.read(8192)
                if not data:
                    break

                buffer += data.decode()
                while buffer.strip():
                    try:
                        buffer = buffer.lstrip()
                        if not buffer:
                            break
                        msg, index = decoder.raw_decode(buffer)
                        buffer = buffer[index:].lstrip()

                        resp_id = msg.get("id")
                        if resp_id is not None and ("result" in msg or "error" in msg):
                            async with self.lock:
                                fut = self.responses.pop(str(resp_id), None)
                            if fut and not fut.done():
                                fut.set_result(msg)
                        elif msg.get("type") == "osc_response":
                            # address = msg.get('address')
                            # args = msg.get('args')
                            # await self.handle_osc_response(address, args)
                            pass

                    except json.JSONDecodeError:
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Error reading response: {e}")
                break

    async def send_rpc_request(self, method: str, params: dict) -> dict:
        """Sends a JSON-RPC request and waits for the response."""
        async with self.semaphore:
            if not self.connected:
                if not await self.connect():
                    return {
                        "ok": False,
                        "error": {
                            "code": "CONNECTION_ERROR",
                            "message": "Not connected to daemon",
                        },
                    }

            async with self.lock:
                self._request_id += 1
                request_id = str(self._request_id)
                future = asyncio.Future()
                self.responses[request_id] = future

            request_obj = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }

            try:
                async with self.write_lock:
                    self.writer.write((json.dumps(request_obj) + "\n").encode())
                    await self.writer.drain()

                try:
                    msg = await asyncio.wait_for(future, timeout=10.0)
                except asyncio.TimeoutError:
                    async with self.lock:
                        self.responses.pop(request_id, None)
                    return {
                        "ok": False,
                        "error": {
                            "code": "TIMEOUT",
                            "message": f"Response timeout for {method}",
                        },
                    }

                if "error" in msg:
                    return {
                        "ok": False,
                        "error": {
                            "code": msg["error"].get("code"),
                            "message": msg["error"].get("message"),
                        },
                    }
                else:
                    return {"ok": True, "data": msg.get("result")}

            except Exception as e:
                self.connected = False
                return {"ok": False, "error": {"code": "EXCEPTION", "message": str(e)}}

    async def send_osc(self, address: str, args: Optional[list] = None) -> dict:
        """Wrapper for sending OSC messages via the daemon."""
        if args is None:
            args = []
        return await self.send_rpc_request(
            "send_message", {"address": address, "args": args}
        )

    async def send_bundle(self, messages: List[Dict[str, Any]]) -> dict:
        """Wrapper for sending OSC bundles via the daemon."""
        return await self.send_rpc_request("send_bundle", {"messages": messages})

    async def close(self):
        """Close the connection."""
        if self.connected:
            self.connected = False
            if self.response_task:
                self.response_task.cancel()
                try:
                    await self.response_task
                except asyncio.CancelledError:
                    pass
            if self.writer:
                self.writer.close()
                try:
                    await self.writer.wait_closed()
                except Exception:
                    pass

    # --- Business Logic Methods ---

    async def run_tool(self, tool_name):
        """CLI runner for AbletonClient tools."""
        tools = {
            "analyze_stems_and_extract_ableton_project_data": self.analyze_stems_and_extract_ableton_project_data,
            "analyze_stems": self.analyze_stems,
            "summarize_stems": self.summarize_stems,
            "get_overview": self.get_overview,
            "extract_ableton_project_data": self.extract_ableton_project_data,
            "get_tracks": self.get_tracks,
            "get_track": self.get_track,
            "get_available_stem_summaries": self.get_available_stem_summaries,
            "get_available_stem_spectrograms": self.get_available_stem_spectrograms,
        }

        if tool_name in tools:
            log_info(f"Calling tool '{tool_name}' directly via CLI...")
            try:
                if not await self.connect():
                    log_error("Could not connect to AbletonOSC daemon. Is it running?")
                    return

                # Note: CLI currently supports only tools without arguments or with defaults
                result = await tools[tool_name]()

                if tool_name not in [
                    "extract_ableton_project_data",
                    "analyze_stems_and_extract_ableton_project_data",
                    "analyze_stems",
                    "summarize_stems",
                ]:
                    print(json.dumps(result, indent=2))
            except Exception as e:
                log_error(f"Tool execution failed: {e}")
            finally:
                await self.close()
        else:
            log_error(f"Unknown tool: {tool_name}")
            log_info(f"Available tools: {', '.join(tools.keys())}")

    @staticmethod
    def _clear_out_folder():
        """
        Clears the output folders (analyses, summaries, spectrograms),
        but keeps the 'project' folder and other critical files.
        """
        out_dir = config.BASE_OUT_DIR
        project_dir = config.PROJECT_DIR

        # Folders to clear explicitly
        folders_to_clear = [
            config.ANALYSES_DIR,
            config.SUMMARIES_DIR,
            config.SPECTROGRAMS_DIR,
            "stems",  # Old folder cleanup
        ]

        try:
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
                return

            for folder_name in folders_to_clear:
                folder_path = os.path.join(out_dir, folder_name)
                if os.path.exists(folder_path) and os.path.isdir(folder_path):
                    log_info(f"Clearing {folder_name} folder...")
                    shutil.rmtree(folder_path)
                    os.makedirs(folder_path, exist_ok=True)

            # Also clear files in BASE_OUT_DIR but not project_dir
            for filename in os.listdir(out_dir):
                file_path = os.path.join(out_dir, filename)
                if filename == project_dir:
                    continue
                if filename in folders_to_clear:
                    continue

                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    log_error(f"Failed to delete file {file_path}: {e}")

        except Exception as e:
            log_error(f"Failed during out directory cleanup: {e}")

    @staticmethod
    def _save_to_out(data: dict):
        """Saves data to the output JSON file."""
        try:
            filename = config.get_project_json_path()
            out_dir = os.path.dirname(filename)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            log_info(f"Result saved to {filename}")
        except Exception as e:
            log_error(f"Failed to save result to file: {e}")

    async def get_overview(self) -> dict:
        """Gets a global overview of the song, including tracks and metadata."""
        try:
            results = {}
            # 1. Global Metadata
            # Number of tracks
            resp = await self.send_osc("/live/song/get/num_tracks")
            num_tracks = 0
            if resp["ok"]:
                num_tracks = resp["data"].get("data", [0])[0]
                results["num_tracks"] = num_tracks

            # Tempo
            resp = await self.send_osc("/live/song/get/tempo")
            if resp["ok"]:
                results["tempo"] = resp["data"].get("data", [0.0])[0]

            # Song length
            resp = await self.send_osc("/live/song/get/song_length")
            if resp["ok"]:
                results["song_length"] = resp["data"].get("data", [0.0])[0]

            # 2. Tracks Data (Bulk)
            if num_tracks > 0:
                properties = [
                    "name",
                    "volume",
                    "panning",
                    "output_meter_level",
                    "is_grouped",
                    "mute",
                    "solo",
                    "is_foldable",
                ]
                tracks_resp = await self.get_tracks(0, num_tracks, properties)
                if tracks_resp["ok"]:
                    results["tracks"] = tracks_resp["data"]
                else:
                    # Fallback to names only if bulk fails
                    log_debug(
                        "Bulk tracks fetch failed in overview, falling back to names."
                    )
                    resp = await self.send_osc("/live/song/get/track_names")
                    if resp["ok"]:
                        names = resp["data"].get("data", [])
                        results["tracks"] = [
                            {"track_index": i, "name": name}
                            for i, name in enumerate(names)
                        ]
            else:
                results["tracks"] = []

            # 3. Locators (Cue Points)
            locators_resp = await self.get_locators()
            if locators_resp["ok"]:
                results["locators"] = locators_resp["data"]

            return {"ok": True, "data": results}
        except Exception as e:
            log_error(f"Error in get_overview: {e}")
            return {"ok": False, "error": str(e)}

    async def get_locators(self) -> dict:
        """Gets all locators (cue points) from the song."""
        try:
            # Get locator names and times
            # AbletonOSC might use /live/song/get/cue_points which returns interleaved list [name1, time1, name2, time2, ...]
            # or it might use /live/song/get/cue_names and /live/song/get/cue_times.
            # Based on the logs, /live/song/get/cue_points/name and /live/song/get/cue_points/time failed.

            # Try /live/song/get/cue_points first as it's the most common plural for cue points
            resp = await self.send_osc("/live/song/get/cue_points")

            if not resp["ok"]:
                # Fallback to separate name/time if /live/song/get/cue_points fails or returns nothing useful
                # (Though the logs showed /name and /time failed, maybe /cue_names exists)
                names_resp = await self.send_osc("/live/song/get/cue_names")
                times_resp = await self.send_osc("/live/song/get/cue_times")

                if not names_resp["ok"] or not times_resp["ok"]:
                    return {
                        "ok": False,
                        "error": "Failed to fetch locators from Ableton",
                    }

                names = names_resp["data"].get("data", [])
                times = times_resp["data"].get("data", [])

                locators = []
                for i in range(min(len(names), len(times))):
                    locators.append(
                        {"index": i, "name": names[i], "time_beats": times[i]}
                    )
                return {"ok": True, "data": locators}

            data = resp["data"].get("data", [])
            locators = []

            # Parse interleaved data if it's [name, time, name, time...]
            # Note: Some versions return [count, name, time...]
            if len(data) > 0:
                start_idx = 0
                # If first element is an integer and it matches the number of subsequent pairs, it might be a count
                if isinstance(data[0], int) and (len(data) - 1) == data[0] * 2:
                    start_idx = 1

                for i in range(start_idx, len(data), 2):
                    if i + 1 < len(data):
                        locators.append(
                            {
                                "index": len(locators),
                                "name": data[i],
                                "time_beats": data[i + 1],
                            }
                        )

            return {"ok": True, "data": locators}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_track_devices(self, track_index: int) -> dict:
        """Gets devices of a track using an OSC bundle."""
        try:
            results = {"track_index": track_index, "devices": []}
            bundle_msgs = [
                {"address": "/live/track/get/devices/name", "args": [track_index]},
                {"address": "/live/track/get/devices/type", "args": [track_index]},
                {
                    "address": "/live/track/get/devices/class_name",
                    "args": [track_index],
                },
            ]

            bundle_resp = await self.send_bundle(bundle_msgs)
            if not bundle_resp["ok"]:
                return bundle_resp

            responses = bundle_resp["data"]
            names_resp = responses[0]
            types_resp = responses[1]
            classes_resp = responses[2]

            if not names_resp.get("ok"):
                return {"ok": False, "error": names_resp.get("error")}

            names_raw = names_resp.get("result", {}).get("data", [])
            types_raw = (
                types_resp.get("result", {}).get("data", [])
                if types_resp.get("ok")
                else []
            )
            classes_raw = (
                classes_resp.get("result", {}).get("data", [])
                if classes_resp.get("ok")
                else []
            )

            # Handle case where AbletonOSC returns track_index as first element
            def skip_index(data, idx):
                if len(data) > 0 and data[0] == idx:
                    return data[1:]
                return data

            names = skip_index(names_raw, track_index)
            types = skip_index(types_raw, track_index)
            classes = skip_index(classes_raw, track_index)

            num_devices = len(names)
            results["num_devices"] = num_devices

            for i in range(num_devices):
                device = {
                    "device_index": i,
                    "name": names[i],
                    "type": types[i] if i < len(types) else "Unknown",
                    "class_name": classes[i] if i < len(classes) else "Unknown",
                    "has_external_side_chain_activated": False,
                }
                results["devices"].append(device)

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_device_parameters(self, track_index: int, device_index: int) -> dict:
        """
        Gets parameters of a device using OSC bundles.
        """
        try:
            results: Dict[str, Any] = {
                "track_index": track_index,
                "device_index": device_index,
                "parameters": [],
            }

            bundle_msgs = [
                {
                    "address": "/live/device/get/name",
                    "args": [track_index, device_index],
                },
                {
                    "address": "/live/device/get/class_name",
                    "args": [track_index, device_index],
                },
                {
                    "address": "/live/device/get/parameters/name",
                    "args": [track_index, device_index],
                },
                {
                    "address": "/live/device/get/parameters/value",
                    "args": [track_index, device_index],
                },
                {
                    "address": "/live/device/get/parameters/min",
                    "args": [track_index, device_index],
                },
                {
                    "address": "/live/device/get/parameters/max",
                    "args": [track_index, device_index],
                },
            ]

            bundle_resp = await self.send_bundle(bundle_msgs)
            if not bundle_resp["ok"]:
                return bundle_resp

            responses = bundle_resp["data"]
            name_resp = responses[0]
            class_resp = responses[1]
            n_resp = responses[2]
            v_resp = responses[3]
            min_resp = responses[4]
            max_resp = responses[5]

            if name_resp.get("ok"):
                data = name_resp.get("result", {}).get("data", [])
                if len(data) >= 3:
                    results["device_name"] = data[2]

            if class_resp.get("ok"):
                data = class_resp.get("result", {}).get("data", [])
                if len(data) >= 3:
                    results["class_name"] = data[2]

            if not n_resp.get("ok"):
                return {"ok": False, "error": n_resp.get("error")}

            p_names_raw = n_resp.get("result", {}).get("data", [])
            p_values_raw = (
                v_resp.get("result", {}).get("data", []) if v_resp.get("ok") else []
            )
            p_mins_raw = (
                min_resp.get("result", {}).get("data", []) if min_resp.get("ok") else []
            )
            p_maxs_raw = (
                max_resp.get("result", {}).get("data", []) if max_resp.get("ok") else []
            )

            if len(p_names_raw) > 0:
                skip = 0
                if (
                    len(p_names_raw) >= 2
                    and p_names_raw[0] == track_index
                    and p_names_raw[1] == device_index
                ):
                    skip = 2
                elif len(p_names_raw) >= 1 and p_names_raw[0] == track_index:
                    skip = 1

                p_names = p_names_raw[skip:]
                p_values = p_values_raw[skip:] if len(p_values_raw) > skip else []
                p_mins = p_mins_raw[skip:] if len(p_mins_raw) > skip else []
                p_maxs = p_maxs_raw[skip:] if len(p_maxs_raw) > skip else []
            else:
                p_names = []
                p_values = []
                p_mins = []
                p_maxs = []

            # Fetch value_strings using an OSC bundle to speed up processing
            bundle_messages = [
                {
                    "address": "/live/device/get/parameter/value_string",
                    "args": [track_index, device_index, i],
                }
                for i in range(len(p_names))
            ]

            p_value_strings = [None] * len(p_names)
            if bundle_messages:
                log_debug(
                    f"Fetching {len(bundle_messages)} value_strings via OSC bundle..."
                )
                # We split into smaller bundles if there are too many parameters to avoid MTU issues
                # 32 messages per bundle is a safe limit for typical UDP packets
                chunk_size = 32
                for j in range(0, len(bundle_messages), chunk_size):
                    chunk = bundle_messages[j : j + chunk_size]
                    bundle_resp = await self.send_bundle(chunk)

                    if bundle_resp["ok"]:
                        # Results are in a list matching the order of messages in the chunk
                        for k, res_item in enumerate(bundle_resp["data"]):
                            if res_item.get("ok"):
                                data = res_item.get("result", {}).get("data", [])
                                # Response format: (track_index, device_index, parameter_index, value_string)
                                if len(data) >= 4:
                                    p_value_strings[j + k] = data[3]

            params_list = []
            for i, name in enumerate(p_names):
                param = {
                    "parameter_index": i,
                    "name": name,
                    "value": p_values[i] if i < len(p_values) else None,
                    "value_string": p_value_strings[i]
                    if i < len(p_value_strings)
                    else None,
                    "min": p_mins[i] if i < len(p_mins) else 0.0,
                    "max": p_maxs[i] if i < len(p_maxs) else 1.0,
                }
                params_list.append(param)

            results["parameters"] = params_list
            results["num_parameters"] = len(params_list)

            # --- Sidechain Routing (Generic detection from parameters) ---
            # This is important for VSTs like Pro-Q 4 where LOM doesn't expose the routing object
            sc_keywords = [
                "Side Chain On",
                "Sidechain On",
                "S/C On",
                "External Side Chain",
            ]
            has_sc_active = any(
                any(kw.lower() in p["name"].lower() for kw in sc_keywords)
                and p["value"] is not None
                and p["value"] > 0.0
                for p in params_list
            )

            results["has_external_side_chain_activated"] = has_sc_active

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_tracks(
        self, index_min: int, index_max: int, properties: List[str] = None
    ) -> dict:
        """
        Bulk request for track properties.
        If 'properties' is None, returns FULL track information (metadata, devices, parameters)
        for each track in the range. Optimized for performance.
        """
        try:
            num_tracks = index_max - index_min
            if num_tracks <= 0:
                return {"ok": True, "data": []}

            # FULL mode: Get all info for each track in range
            if properties is None:
                log_debug(
                    f"Fetching FULL data for tracks {index_min} to {index_max} in optimized parallel mode..."
                )

                # 1. Optimized Bulk Meta Fetch for the whole range in ONE OSC call
                meta_props = [
                    "name",
                    "volume",
                    "panning",
                    "mute",
                    "solo",
                    "is_grouped",
                    "is_foldable",
                    "output_meter_level",
                ]
                meta_resp = await self.get_tracks(index_min, index_max, meta_props)
                if not meta_resp["ok"]:
                    return meta_resp

                tracks_data = meta_resp["data"]

                # 2. Parallel device and parameter fetch for each track
                async def fetch_devices_and_params(t_data):
                    t_idx = t_data["track_index"]
                    # Fetch devices
                    dev_resp = await self.get_track_devices(t_idx)
                    if not dev_resp["ok"]:
                        t_data["devices"] = []
                        return t_data

                    devices = dev_resp["data"].get("devices", [])
                    t_data["devices"] = devices

                    # Fetch parameters for all devices in parallel
                    if devices:
                        param_tasks = [
                            self.get_device_parameters(t_idx, i)
                            for i in range(len(devices))
                        ]
                        param_results = await asyncio.gather(*param_tasks)
                        for i, p_res in enumerate(param_results):
                            if p_res["ok"]:
                                devices[i]["parameters"] = p_res["data"].get(
                                    "parameters", []
                                )
                                devices[i]["has_external_side_chain_activated"] = p_res[
                                    "data"
                                ].get("has_external_side_chain_activated", False)
                            else:
                                devices[i]["parameters"] = []
                    return t_data

                fetch_tasks = [fetch_devices_and_params(td) for td in tracks_data]
                final_results = await asyncio.gather(*fetch_tasks)
                return {"ok": True, "data": final_results}

            results = [{"track_index": index_min + i} for i in range(num_tracks)]

            # volume and panning are MixerDevice properties and NOT supported by track_data bulk API
            incompatible = {"volume", "panning"}

            bulk_candidates = [p for p in properties if p not in incompatible]
            to_fetch_individually = [p for p in properties if p in incompatible]

            # 1. Fetch bulk properties if any
            if bulk_candidates:
                api_props = [f"track.{p}" for p in bulk_candidates]
                args = [index_min, index_max] + api_props

                log_debug(
                    f"Sending bulk track_data request for {len(bulk_candidates)} properties..."
                )
                resp = await self.send_osc("/live/song/get/track_data", args)

                if resp["ok"]:
                    data = resp["data"].get("data", [])

                    # Response format: [track_0_p1, track_0_p2, ..., track_1_p1, ...]
                    # Check for Range Echo (though track_data usually doesn't echo range)
                    start_idx = 0
                    if len(data) >= 2 and data[0] == index_min and data[1] == index_max:
                        start_idx = 2

                    actual_data = data[start_idx:]
                    expected_total = num_tracks * len(bulk_candidates)

                    if len(actual_data) >= expected_total:
                        for i in range(num_tracks):
                            for j, prop in enumerate(bulk_candidates):
                                val_idx = i * len(bulk_candidates) + j
                                results[i][prop] = actual_data[val_idx]
                    else:
                        log_debug(
                            f"Bulk data too short ({len(actual_data)} < {expected_total}), falling back."
                        )
                        to_fetch_individually.extend(bulk_candidates)
                else:
                    log_debug(
                        f"Bulk request failed: {resp.get('error')}, falling back."
                    )
                    to_fetch_individually.extend(bulk_candidates)

            # 2. Fetch individual properties
            if to_fetch_individually:
                log_debug(
                    f"Fetching {len(to_fetch_individually)} properties individually for {num_tracks} tracks..."
                )
                individual_resp = await self._get_tracks_fallback(
                    index_min, index_max, to_fetch_individually
                )
                if individual_resp["ok"]:
                    indiv_data = individual_resp["data"]
                    for i in range(num_tracks):
                        for prop in to_fetch_individually:
                            if prop in indiv_data[i]:
                                results[i][prop] = indiv_data[i][prop]

            return {"ok": True, "data": results}
        except Exception as e:
            log_error(f"Error in get_tracks: {e}")
            return {"ok": False, "error": str(e)}

    async def get_track(self, track_index: int) -> dict:
        """
        Gets full track information including metadata, devices and all parameters.
        Highly optimized with bulk requests and parallel execution.
        """
        try:
            # 1. Fetch Track Metadata (Volume, Panning, Name, etc.)
            properties = [
                "name",
                "volume",
                "panning",
                "mute",
                "solo",
                "is_grouped",
                "is_foldable",
                "output_meter_level",
            ]
            meta_resp = await self.get_tracks(
                track_index, track_index + 1, properties
            )

            if not meta_resp["ok"] or not meta_resp["data"]:
                return {
                    "ok": False,
                    "error": f"Failed to fetch track metadata: {meta_resp.get('error')}",
                }

            track_data = meta_resp["data"][0]
            track_data["track_index"] = track_index

            # 2. Fetch Devices
            devices_resp = await self.get_track_devices(track_index)
            if not devices_resp["ok"]:
                return {
                    "ok": False,
                    "error": f"Failed to fetch devices: {devices_resp.get('error')}",
                }

            devices = devices_resp["data"].get("devices", [])
            track_data["devices"] = devices

            # 3. Fetch Parameters for all devices in parallel
            if devices:
                log_debug(
                    f"Fetching parameters for {len(devices)} devices in parallel..."
                )
                param_tasks = [
                    self.get_device_parameters(track_index, i)
                    for i in range(len(devices))
                ]
                param_results = await asyncio.gather(*param_tasks)

                for i, p_res in enumerate(param_results):
                    if p_res["ok"]:
                        # Merge parameter data into device object
                        devices[i]["parameters"] = p_res["data"].get("parameters", [])
                        devices[i]["has_external_side_chain_activated"] = p_res[
                            "data"
                        ].get("has_external_side_chain_activated", False)
                    else:
                        log_error(
                            f"Failed to fetch parameters for device {i}: {p_res.get('error')}"
                        )
                        devices[i]["parameters"] = []

            return {"ok": True, "data": track_data}
        except Exception as e:
            log_error(f"Error in get_track: {e}")
            return {"ok": False, "error": str(e)}

    async def set_device_parameter(
        self, track_index: int, device_index: int, parameter_index: int, value: float
    ) -> dict:
        """
        Sets a parameter value for a device.
        :param track_index: The index of the track.
        :param device_index: The index of the device on the track.
        :param parameter_index: The index of the parameter on the device.
        :param value: The new value for the parameter (usually 0.0 to 1.0).
        """
        return await self.send_osc(
            "/live/device/set/parameter/value",
            [track_index, device_index, parameter_index, value],
        )

    async def set_device_parameters(
        self, track_index: int, device_index: int, values: List[float]
    ) -> dict:
        """
        Sets multiple parameter values for a device in bulk.
        :param track_index: The index of the track.
        :param device_index: The index of the device on the track.
        :param values: A list of new values for the parameters.
        """
        return await self.send_osc(
            "/live/device/set/parameters/value",
            [track_index, device_index] + list(values),
        )

    async def set_track_volume(self, track_index: int, value: float) -> dict:
        """
        Sets the volume of a track.
        :param track_index: The index of the track.
        :param value: The new volume value (0.0 to 1.0).
        """
        return await self.send_osc("/live/track/set/volume", [track_index, value])

    async def set_track_panning(self, track_index: int, value: float) -> dict:
        """
        Sets the panning of a track.
        :param track_index: The index of the track.
        :param value: The new panning value (-1.0 to 1.0).
        """
        return await self.send_osc("/live/track/set/panning", [track_index, value])

    async def set_track_mute(self, track_index: int, mute: bool) -> dict:
        """
        Sets the mute state of a track.
        :param track_index: The index of the track.
        :param mute: True to mute, False to unmute.
        """
        return await self.send_osc(
            "/live/track/set/mute", [track_index, 1 if mute else 0]
        )

    async def set_track_solo(self, track_index: int, solo: bool) -> dict:
        """
        Sets the solo state of a track.
        :param track_index: The index of the track.
        :param solo: True to solo, False to unsolo.
        """
        return await self.send_osc(
            "/live/track/set/solo", [track_index, 1 if solo else 0]
        )

    async def _get_tracks_fallback(
        self, index_min: int, index_max: int, properties: List[str]
    ) -> dict:
        """Individual request fallback for bulk track properties using OSC bundles."""
        num_tracks = index_max - index_min
        results = [{"track_index": index_min + i} for i in range(num_tracks)]

        bundle_messages = []
        message_info = []

        for prop in properties:
            for i in range(num_tracks):
                t_idx = index_min + i
                bundle_messages.append(
                    {"address": f"/live/track/get/{prop}", "args": [t_idx]}
                )
                message_info.append((i, prop))

        if not bundle_messages:
            return {"ok": True, "data": results}

        log_debug(
            f"Fetching {len(bundle_messages)} track properties via OSC bundles..."
        )
        # Split into smaller bundles to avoid MTU issues
        chunk_size = 32
        for j in range(0, len(bundle_messages), chunk_size):
            chunk = bundle_messages[j : j + chunk_size]
            bundle_resp = await self.send_bundle(chunk)

            if bundle_resp["ok"]:
                for k, res_item in enumerate(bundle_resp["data"]):
                    if res_item.get("ok"):
                        idx, prop = message_info[j + k]
                        data = res_item.get("result", {}).get("data", [])
                        # Response format: (track_index, property_value)
                        if len(data) >= 2:
                            results[idx][prop] = data[1]
                        elif len(data) == 1:
                            results[idx][prop] = data[0]

        return {"ok": True, "data": results}

    @staticmethod
    async def _analyze_stems_pipeline(summary_only: bool = False):
        """Internal audio analysis pipeline."""
        src_dir = config.STEMS_SOURCE_DIR
        ext = f".{config.PREFERRED_AUDIO_FORMAT.lower()}"

        if not os.path.exists(src_dir):
            log_error(f"STEMS_SOURCE_DIR does not exist: {src_dir}")
            return False

        audio_files = [
            os.path.join(src_dir, f)
            for f in os.listdir(src_dir)
            if f.lower().endswith(ext)
        ]
        if audio_files:
            log_debug(
                f"Starting parallel analysis (summary_only={summary_only}) of {len(audio_files)} stems from {src_dir}..."
            )
            analysis_tasks = [
                asyncio.to_thread(process_audio_file, f, "", summary_only)
                for f in audio_files
            ]
            await asyncio.gather(*analysis_tasks)
            log_debug("Parallel analysis finished.")
        else:
            log_info(f"No audio files with extension {ext} found in {src_dir}")

        return True

    async def _extract_project_data_internal(self) -> dict:
        """Internal project data extraction logic."""
        try:
            song_resp = await self.get_overview()
            if not song_resp["ok"]:
                self._save_to_out(song_resp)
                return song_resp

            num_tracks = song_resp["data"].get("num_tracks", 0)
            tracks_list: List[Dict[str, Any]] = []
            project_data = {
                "project": {
                    "tempo": song_resp["data"].get("tempo"),
                    "num_tracks": num_tracks,
                    "song_length": song_resp["data"].get("song_length"),
                    "locators": song_resp["data"].get("locators", []),
                },
                "tracks": tracks_list,
            }

            if num_tracks == 0:
                result = {"ok": True, "data": project_data}
                self._save_to_out(result)
                return result

            properties = [
                "name",
                "volume",
                "panning",
                "mute",
                "solo",
                "output_meter_level",
                "is_foldable",
                "is_grouped",
            ]
            tracks_bulk_resp = await self.get_tracks(0, num_tracks, properties)

            if not tracks_bulk_resp["ok"]:
                result = {
                    "ok": False,
                    "error": tracks_bulk_resp.get("error"),
                    "partial_data": project_data,
                }
                self._save_to_out(result)
                return result

            tracks_data = tracks_bulk_resp["data"]

            device_tasks = [
                self.get_track_devices(t["track_index"]) for t in tracks_data
            ]
            device_responses = await asyncio.gather(*device_tasks)

            track_to_devices = {}
            for i, resp in enumerate(device_responses):
                t_idx = tracks_data[i]["track_index"]
                if resp["ok"]:
                    track_to_devices[t_idx] = resp["data"].get("devices", [])
                else:
                    track_to_devices[t_idx] = []

            rel_classes = config.RELEVANT_DEVICE_CLASSES
            rel_names = config.RELEVANT_DEVICE_NAMES
            param_tasks = []
            param_task_info = []

            for track_data in tracks_data:
                t_idx = track_data["track_index"]
                track_data["devices"] = track_to_devices.get(t_idx, [])

                for device in track_data["devices"]:
                    class_name = device.get("class_name")
                    name = device.get("name")
                    is_rel = class_name in rel_classes or (
                        name
                        and any(
                            rn == name or f" {rn}" in name or f"{rn} " in name
                            for rn in rel_names
                        )
                    )

                    if is_rel:
                        param_tasks.append(
                            self.get_device_parameters(t_idx, device["device_index"])
                        )
                        param_task_info.append((t_idx, device["device_index"]))

                tracks_list.append(track_data)

            if param_tasks:
                param_responses = await asyncio.gather(*param_tasks)
                track_lookup = {t["track_index"]: t for t in tracks_list}

                for p_resp, (t_idx, d_idx) in zip(param_responses, param_task_info):
                    if p_resp["ok"]:
                        track = track_lookup.get(t_idx)
                        if track:
                            for d in track.get("devices", []):
                                if d.get("device_index") == d_idx:
                                    d.update(p_resp["data"])
                                    break

            result = {
                "ok": True,
                "data": project_data,
                "description": "Project data successfully extracted and saved.",
            }
            self._save_to_out(result)
            return result
        except Exception as e:
            err_res = {"ok": False, "error": str(e)}
            self._save_to_out(err_res)
            return err_res

    def _format_duration(self, duration: float) -> str:
        """Helper to format duration in a human-readable way."""
        if duration >= 60:
            m, s = divmod(int(duration), 60)
            return f"{m}m {s}s"
        return f"{duration:.2f}s"

    async def analyze_stems_and_extract_ableton_project_data(self) -> dict:
        """
        Full Pipeline: Executes audio analysis of stems AND extracts project data.
        """
        log_info("Starting FULL ANALYSIS & DATA EXTRACTION pipeline...")
        start_time = time.time()
        try:
            self._clear_out_folder()
            analysis_task = asyncio.create_task(self._analyze_stems_pipeline())
            extraction_task = asyncio.create_task(self._extract_project_data_internal())
            await asyncio.gather(analysis_task, extraction_task)
            return extraction_task.result()
        finally:
            duration = time.time() - start_time
            log_info(f"Pipeline finished. Duration: {self._format_duration(duration)}")

    async def analyze_stems(self) -> dict:
        """
        Executes the FULL audio analysis of stems (spectrograms + full + summary).
        """
        log_info("Starting FULL STEM ANALYSIS...")
        start_time = time.time()
        try:
            self._clear_out_folder()
            await self._analyze_stems_pipeline(summary_only=False)
            return {"ok": True, "description": "Full stem analysis finished."}
        finally:
            duration = time.time() - start_time
            log_info(
                f"Full stem analysis finished. Duration: {self._format_duration(duration)}"
            )

    async def summarize_stems(self) -> dict:
        """
        Executes ONLY the summary audio analysis of stems (fast).
        """
        log_info("Starting STEM SUMMARY ONLY...")
        start_time = time.time()
        try:
            self._clear_out_folder()
            await self._analyze_stems_pipeline(summary_only=True)
            return {"ok": True, "description": "Stem summary finished."}
        finally:
            duration = time.time() - start_time
            log_info(
                f"Stem summary finished. Duration: {self._format_duration(duration)}"
            )

    async def extract_ableton_project_data(self) -> dict:
        """
        Extracts ONLY the project metadata, tracks, and devices
        and saves them as JSON, without audio analysis.
        """
        log_info("Starting PROJECT DATA EXTRACTION (metadata only)...")
        start_time = time.time()
        try:
            return await self._extract_project_data_internal()
        finally:
            duration = time.time() - start_time
            log_info(
                f"Data extraction finished. Duration: {self._format_duration(duration)}"
            )

    async def get_available_stem_summaries(self) -> List[str]:
        """
        Scans the summaries directory for available stem analysis JSON files.
        Returns a list of track names, including those with project-name prefixes.
        """
        summaries_dir = config.get_summaries_path()
        if not os.path.exists(summaries_dir):
            return []

        files = os.listdir(summaries_dir)
        # Match filenames like "TrackName.summary.json" or "ProjectName TrackName.summary.json"
        stems = []
        for f in files:
            if f.endswith(".summary.json"):
                # Handle both "name.summary.json" and "name.01.summary.json"
                name = f.replace(".summary.json", "")
                # If it ends with .XX (chunk suffix), strip it for the stem list
                name = re.sub(r"\.\d{2}$", "", name)
                if name not in stems:
                    stems.append(name)
        return sorted(stems)

    async def get_available_stem_spectrograms(self) -> List[str]:
        """
        Scans the spectrograms directory for available spectrogram WebP files.
        Returns a list of track names, including those with project-name prefixes.
        """
        spectrograms_dir = config.get_spectrograms_path()
        if not os.path.exists(spectrograms_dir):
            return []

        files = os.listdir(spectrograms_dir)
        # Match filenames like "TrackName.spectrogram.webp" or "ProjectName TrackName.spectrogram.webp"
        spectrograms = []
        for f in files:
            if f.endswith(".spectrogram.webp"):
                name = f.replace(".spectrogram.webp", "")
                spectrograms.append(name)
        return sorted(spectrograms)


if __name__ == "__main__":
    client = AbletonClient()
    if len(sys.argv) > 1:
        asyncio.run(client.run_tool(sys.argv[1]))
    else:
        log_info("AbletonClient CLI usage: uv run ableton_client.py <tool_name>")
        log_info("Example: uv run ableton_client.py extract_ableton_project_data")
