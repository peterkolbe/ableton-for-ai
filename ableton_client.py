import asyncio
import json
import os
import shutil
import sys
import time
from typing import List, Optional, Dict, Any

import config
from audio_processor import process_audio_file

def log_info(message: str):
    """Prints info messages to stderr."""
    print(f"[INFO] {message}", file=sys.stderr)

def log_debug(message: str):
    """Prints debug messages to stderr if LOG_LEVEL is DEBUG."""
    if config.LOG_LEVEL == "DEBUG":
        print(f"[DEBUG] {message}", file=sys.stderr)

def log_error(message: str):
    """Prints error messages to stderr."""
    print(f"[ERROR] {message}", file=sys.stderr)

class AbletonClient:
    def __init__(self, host='127.0.0.1', port=65432):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False
        self.responses = {}  # Store futures keyed by (request_id)
        self.lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()  # Lock for socket write operations
        self.semaphore = asyncio.Semaphore(20)  # Limit parallel OSC requests
        self._request_id = 0
        self.response_task = None

    async def connect(self):
        """Connect to the OSC daemon via asyncio."""
        if not self.connected:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
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

                        resp_id = msg.get('id')
                        if resp_id is not None and ('result' in msg or 'error' in msg):
                            async with self.lock:
                                fut = self.responses.pop(str(resp_id), None)
                            if fut and not fut.done():
                                fut.set_result(msg)
                        elif msg.get('type') == 'osc_response':
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
                    return {'ok': False, 'error': {'code': 'CONNECTION_ERROR', 'message': 'Not connected to daemon'}}

            async with self.lock:
                self._request_id += 1
                request_id = str(self._request_id)
                future = asyncio.Future()
                self.responses[request_id] = future

            request_obj = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params
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
                    return {'ok': False, 'error': {'code': 'TIMEOUT', 'message': f'Response timeout for {method}'}}

                if 'error' in msg:
                    return {
                        'ok': False,
                        'error': {
                            'code': msg['error'].get('code'),
                            'message': msg['error'].get('message')
                        }
                    }
                else:
                    return {
                        'ok': True,
                        'data': msg.get('result')
                    }

            except Exception as e:
                self.connected = False
                return {'ok': False, 'error': {'code': 'EXCEPTION', 'message': str(e)}}

    async def send_osc(self, address: str, args: Optional[list] = None) -> dict:
        """Wrapper for sending OSC messages via the daemon."""
        if args is None:
            args = []
        return await self.send_rpc_request("send_message", {"address": address, "args": args})

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
                except:
                    pass

    # --- Business Logic Methods ---

    async def run_tool(self, tool_name):
        """CLI runner for AbletonClient tools."""
        tools = {
            "get_track_names": self.get_track_names,
            "get_song_overview": self.get_song_overview,
            "get_track_overview": self.get_track_overview,
            "get_track_devices": self.get_track_devices,
            "get_device_parameters": self.get_device_parameters,
            "get_all_mix_relevant_devices": self.get_all_mix_relevant_devices,
            "snapshot_mix_and_save_as_json": self.snapshot_mix_and_save_as_json,
            "get_tracks_bulk": self.get_tracks_bulk
        }

        if tool_name in tools:
            log_info(f"Calling tool '{tool_name}' directly via CLI...")
            try:
                if not await self.connect():
                    log_error("Could not connect to AbletonOSC daemon. Is it running?")
                    return

                # Note: CLI currently supports only tools without arguments or with defaults
                result = await tools[tool_name]()

                if tool_name != "snapshot_mix_and_save_as_json":
                    print(json.dumps(result, indent=2))
            except Exception as e:
                log_error(f"Tool execution failed: {e}")
            finally:
                await self.close()
        else:
            log_error(f"Unknown tool: {tool_name}")
            log_info(f"Available tools: {', '.join(tools.keys())}")

    def _clear_out_folder(self):
        """Clears the output folder."""
        out_dir = config.BASE_OUT_DIR
        try:
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
                return

            for filename in os.listdir(out_dir):
                file_path = os.path.join(out_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    log_error(f"Failed to delete {file_path}: {e}")
        except Exception as e:
            log_error(f"Failed to clear out directory: {e}")

    def _copy_stems(self):
        """Copies stems to the output folder."""
        try:
            out_dir = config.BASE_OUT_DIR
            src_dir = config.STEMS_SOURCE_DIR
            ext = f".{config.PREFERRED_AUDIO_FORMAT.lower()}"

            if not os.path.exists(src_dir):
                log_debug(f"Source directory for stems not found: {src_dir}")
                return 0

            count = 0
            for filename in os.listdir(src_dir):
                if filename.lower().endswith(ext):
                    try:
                        shutil.copy2(os.path.join(src_dir, filename), os.path.join(out_dir, filename))
                        count += 1
                    except Exception as e:
                        log_error(f"Failed to copy {filename}: {e}")

            if count > 0:
                log_info(f"Copied {count} {config.PREFERRED_AUDIO_FORMAT} stem files to {out_dir}/")
            return count
        except Exception as e:
            log_error(f"Failed to copy stems: {e}")
            return 0

    def _save_to_out(self, data: dict):
        """Saves data to the output JSON file."""
        try:
            if not os.path.exists(config.BASE_OUT_DIR):
                os.makedirs(config.BASE_OUT_DIR)

            filename = config.get_snapshot_json_path()

            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            log_info(f"Result saved to {filename}")
        except Exception as e:
            log_error(f"Failed to save result to file: {e}")

    async def get_track_names(self, index_min: Optional[int] = None, index_max: Optional[int] = None) -> dict:
        """Gets the names of tracks."""
        try:
            args = []
            if index_min is not None and index_max is not None:
                args = [index_min, index_max]

            response = await self.send_osc("/live/song/get/track_names", args)

            if response['ok']:
                data = response['data'].get('data', [])
                if not data:
                    return {"ok": True, "data": {"tracks": []}, "description": "No tracks found"}
                else:
                    tracks = []
                    start_idx = index_min if index_min is not None else 0
                    for i, name in enumerate(data):
                        tracks.append({"index": start_idx + i, "name": name})

                    return {
                        "ok": True,
                        "data": {
                            "track_count": len(tracks),
                            "tracks": tracks
                        },
                        "description": f"Found {len(tracks)} tracks"
                    }
            return response
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_song_overview(self) -> dict:
        """Gets a global overview of the song."""
        try:
            results = {}
            # Num tracks
            resp = await self.send_osc("/live/song/get/num_tracks")
            if resp['ok']:
                results['num_tracks'] = resp['data'].get('data', [0])[0]

            # Track names
            resp = await self.send_osc("/live/song/get/track_names")
            if resp['ok']:
                names = resp['data'].get('data', [])
                results['track_names'] = [{"index": i, "name": name} for i, name in enumerate(names)]

            # Tempo
            resp = await self.send_osc("/live/song/get/tempo")
            if resp['ok']:
                results['tempo'] = resp['data'].get('data', [0.0])[0]

            # Song length
            resp = await self.send_osc("/live/song/get/song_length")
            if resp['ok']:
                results['song_length'] = resp['data'].get('data', [0.0])[0]

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_track_overview(self, track_index: int) -> dict:
        """Gets overview of a single track."""
        try:
            results = {"track_index": track_index}
            properties = [
                ("name", "/live/track/get/name"),
                ("volume", "/live/track/get/volume"),
                ("panning", "/live/track/get/panning"),
                ("output_meter_level", "/live/track/get/output_meter_level"),
                ("is_grouped", "/live/track/get/is_grouped"),
                ("mute", "/live/track/get/mute"),
                ("solo", "/live/track/get/solo"),
                ("is_foldable", "/live/track/get/is_foldable")
            ]

            for key, addr in properties:
                resp = await self.send_osc(addr, [track_index])
                if resp['ok']:
                    data = resp['data'].get('data', [])
                    if len(data) >= 2:
                        results[key] = data[1]
                    elif len(data) == 1:
                        results[key] = data[0]

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_track_devices(self, track_index: int) -> dict:
        """Gets devices of a track."""
        try:
            results = {"track_index": track_index, "devices": []}
            names_resp = await self.send_osc("/live/track/get/devices/name", [track_index])
            types_resp = await self.send_osc("/live/track/get/devices/type", [track_index])
            classes_resp = await self.send_osc("/live/track/get/devices/class_name", [track_index])

            if not names_resp['ok']:
                return names_resp

            names = names_resp['data'].get('data', [])[1:]
            types = types_resp['data'].get('data', [])[1:] if types_resp['ok'] else []
            classes = classes_resp['data'].get('data', [])[1:] if classes_resp['ok'] else []

            num_devices = len(names)
            results["num_devices"] = num_devices

            for i in range(num_devices):
                device = {
                    "device_index": i,
                    "name": names[i],
                    "type": types[i] if i < len(types) else "Unknown",
                    "class_name": classes[i] if i < len(classes) else "Unknown"
                }
                results["devices"].append(device)

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_device_parameters(self, track_index: int, device_index: int) -> dict:
        """Gets parameters of a device."""
        try:
            results: Dict[str, Any] = {
                "track_index": track_index,
                "device_index": device_index,
                "parameters": []
            }

            name_resp = await self.send_osc("/live/device/get/name", [track_index, device_index])
            class_resp = await self.send_osc("/live/device/get/class_name", [track_index, device_index])

            if name_resp['ok']:
                data = name_resp['data'].get('data', [])
                if len(data) >= 3:
                    results["device_name"] = data[2]

            if class_resp['ok']:
                data = class_resp['data'].get('data', [])
                if len(data) >= 3:
                    results["class_name"] = data[2]

            n_resp = await self.send_osc("/live/device/get/parameters/name", [track_index, device_index])
            v_resp = await self.send_osc("/live/device/get/parameters/value", [track_index, device_index])

            if not n_resp['ok']:
                return n_resp
            
            p_names_raw = n_resp.get('data', {}).get('data', [])
            p_values_raw = v_resp.get('data', {}).get('data', []) if v_resp['ok'] else []

            if len(p_names_raw) > 0:
                skip = 0
                if len(p_names_raw) >= 2 and p_names_raw[0] == track_index and p_names_raw[1] == device_index:
                    skip = 2
                elif len(p_names_raw) >= 1 and p_names_raw[0] == track_index:
                    skip = 1

                p_names = p_names_raw[skip:]
                p_values = p_values_raw[skip:] if len(p_values_raw) > skip else []
            else:
                p_names = []
                p_values = []

            params_list = []
            for i, name in enumerate(p_names):
                param = {
                    "parameter_index": i,
                    "name": name,
                    "value": p_values[i] if i < len(p_values) else None
                }
                params_list.append(param)

            results["parameters"] = params_list
            results["num_parameters"] = len(params_list)

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_all_mix_relevant_devices(self) -> dict:
        """Gets all mix relevant devices across all tracks."""
        try:
            relevant_classes = config.RELEVANT_DEVICE_CLASSES
            relevant_names = config.RELEVANT_DEVICE_NAMES

            names_resp = await self.send_osc("/live/song/get/track_names")
            if not names_resp['ok']:
                return names_resp
            track_names = names_resp['data'].get('data', [])
            num_tracks = len(track_names)

            results = []

            for t_idx in range(num_tracks):
                t_name = track_names[t_idx]
                track_entry = {"track_index": t_idx, "track_name": t_name, "relevant_devices": []}

                dev_names_resp = await self.send_osc("/live/track/get/devices/name", [t_idx])
                dev_classes_resp = await self.send_osc("/live/track/get/devices/class_name", [t_idx])

                if dev_names_resp['ok'] and dev_classes_resp['ok']:
                    dev_names = dev_names_resp['data'].get('data', [])[1:]
                    dev_classes = dev_classes_resp['data'].get('data', [])[1:]

                    for d_idx, (name, class_name) in enumerate(zip(dev_names, dev_classes)):
                        is_relevant = class_name in relevant_classes or (
                            name and any(rn == name or f" {rn}" in name or f"{rn} " in name for rn in relevant_names))

                        if is_relevant:
                            device_info = {
                                "device_index": d_idx,
                                "name": name,
                                "class_name": class_name
                            }
                            params_resp = await self.get_device_parameters(t_idx, d_idx)
                            if params_resp['ok']:
                                device_info["parameters"] = params_resp['data'].get("parameters", [])

                            track_entry["relevant_devices"].append(device_info)

                if track_entry["relevant_devices"]:
                    results.append(track_entry)

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_tracks_bulk(self, index_min: int, index_max: int, properties: List[str]) -> dict:
        """Bulk request for track properties."""
        try:
            num_tracks = index_max - index_min
            results = [{"track_index": index_min + i} for i in range(num_tracks)]

            plural_map = {
                "name": "/live/song/get/track_names",
            }

            tasks = []
            task_info = []

            for prop in properties:
                addr = plural_map.get(prop)
                if addr:
                    tasks.append(self.send_osc(addr))
                    task_info.append((None, prop, True))
                else:
                    for i in range(num_tracks):
                        t_idx = index_min + i
                        tasks.append(self.send_osc(f"/live/track/get/{prop}", [t_idx]))
                        task_info.append((i, prop, False))

            if not tasks:
                return {"ok": True, "data": results}

            responses = await asyncio.gather(*tasks)

            for resp, (idx, prop, is_bulk) in zip(responses, task_info):
                if not resp['ok']:
                    continue

                data = resp['data'].get('data', [])
                if is_bulk:
                    for i in range(num_tracks):
                        if i < len(data):
                            results[i][prop] = data[i]
                else:
                    if len(data) >= 2:
                        results[idx][prop] = data[1]
                    elif len(data) == 1:
                        results[idx][prop] = data[0]

            return {"ok": True, "data": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _run_audio_analysis_pipeline(self):
        """Internal audio analysis pipeline."""
        await asyncio.to_thread(self._copy_stems)

        out_dir = config.BASE_OUT_DIR
        ext = f".{config.PREFERRED_AUDIO_FORMAT.lower()}"
        if os.path.exists(out_dir):
            audio_files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.lower().endswith(ext)]
            if audio_files:
                log_debug(f"Starting parallel analysis of {len(audio_files)} stems...")
                analysis_tasks = [asyncio.to_thread(process_audio_file, f) for f in audio_files]
                await asyncio.gather(*analysis_tasks)
                log_debug(f"Parallel analysis finished.")
        return True

    async def _get_mix_snapshot_internal(self) -> dict:
        """Internal mix snapshot logic."""
        try:
            song_resp = await self.get_song_overview()
            if not song_resp['ok']:
                self._save_to_out(song_resp)
                return song_resp

            num_tracks = song_resp['data'].get('num_tracks', 0)
            tracks_list: List[Dict[str, Any]] = []
            snapshot = {
                "project": {
                    "tempo": song_resp['data'].get('tempo'),
                    "num_tracks": num_tracks,
                    "song_length": song_resp['data'].get('song_length')
                },
                "tracks": tracks_list
            }

            if num_tracks == 0:
                result = {"ok": True, "data": snapshot}
                self._save_to_out(result)
                return result

            properties = ["name", "volume", "panning", "mute", "solo", "output_meter_level", "is_foldable", "is_grouped"]
            tracks_bulk_resp = await self.get_tracks_bulk(0, num_tracks, properties)

            if not tracks_bulk_resp['ok']:
                result = {"ok": False, "error": tracks_bulk_resp.get('error'), "partial_data": snapshot}
                self._save_to_out(result)
                return result

            tracks_data = tracks_bulk_resp['data']
            device_tasks = [self.get_track_devices(t["track_index"]) for t in tracks_data]
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
                    is_rel = class_name in rel_classes or (name and any(rn == name or f" {rn}" in name or f"{rn} " in name for rn in rel_names))

                    if is_rel:
                        param_tasks.append(self.get_device_parameters(t_idx, device["device_index"]))
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
                                    d["parameters"] = p_resp['data'].get("parameters", [])
                                    break

            result = {
                "ok": True,
                "data": snapshot,
                "description": "Snapshot successfully created and saved."
            }
            self._save_to_out(result)
            return result
        except Exception as e:
            err_res = {"ok": False, "error": str(e)}
            self._save_to_out(err_res)
            return err_res

    async def snapshot_mix_and_save_as_json(self) -> dict:
        """Ultimate snapshot tool logic."""
        log_info(f"Starting ULTIMATE MIX SNAPSHOT pipeline...")
        start_time = time.time()
        try:
            self._clear_out_folder()
            analysis_task = asyncio.create_task(self._run_audio_analysis_pipeline())
            snapshot_task = asyncio.create_task(self._get_mix_snapshot_internal())
            await asyncio.gather(analysis_task, snapshot_task)
            return snapshot_task.result()
        finally:
            duration = time.time() - start_time
            m, s = divmod(int(duration), 60)
            log_info(f"Pipeline finished. Duration: {m}m {s}s")

if __name__ == "__main__":
    client = AbletonClient()
    if len(sys.argv) > 1:
        asyncio.run(client.run_tool(sys.argv[1]))
    else:
        log_info("AbletonClient CLI usage: uv run ableton_client.py <tool_name>")
        log_info("Example: uv run ableton_client.py snapshot_mix_and_save_as_json")
