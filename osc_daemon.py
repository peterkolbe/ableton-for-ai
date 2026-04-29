import asyncio
import json
import sys
import errno
from typing import Dict

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder


class AbletonOSCDaemon:
  def __init__(self,
               socket_host='127.0.0.1', socket_port=65432,
               ableton_host='127.0.0.1', ableton_port=11000,
               receive_port=11001):
    self.socket_host = socket_host
    self.socket_port = socket_port
    self.ableton_host = ableton_host
    self.ableton_port = ableton_port
    self.receive_port = receive_port

    # Initialize OSC client for Ableton
    self.osc_client = SimpleUDPClient(ableton_host, ableton_port)

    # OSC Server instance (initialized in start)
    self.osc_server = None

    # Store active connections waiting for responses
    # Each entry is a list of tuples (future, original_args)
    self.pending_responses: Dict[str, list[tuple[asyncio.Future, list]]] = {}

    # Initialize OSC server dispatcher
    self.dispatcher = Dispatcher()
    self.dispatcher.set_default_handler(self.handle_ableton_message)

  def handle_ableton_message(self, address: str, *args):
    """Handle incoming OSC messages from Ableton."""
    print(f"[ABLETON MESSAGE] Address: {address}, Args: {args}")

    # Handle errors reported by Ableton
    if address == "/live/error" and args:
      error_msg = str(args[0])
      # If the error message contains the unknown address, we try to find it
      # Format usually: "Unknown OSC address: /live/..."
      if "Unknown OSC address: " in error_msg:
        unknown_addr = error_msg.replace("Unknown OSC address: ", "").strip()
        if unknown_addr in self.pending_responses:
          candidates = self.pending_responses[unknown_addr]
          for future, _ in candidates:
            if not future.done():
              future.set_exception(Exception(f"Ableton error: {error_msg}"))
          del self.pending_responses[unknown_addr]
          return

      # Fallback: if we have any pending responses, send the error to the last one
      # as it's likely the cause of the error.
      if self.pending_responses:
        # Get the most recently added pending response
        last_addr = list(self.pending_responses.keys())[-1]
        candidates = self.pending_responses[last_addr]
        if candidates:
          fut, _ = candidates.pop(0)
          if not fut.done():
            fut.set_exception(Exception(f"Ableton error: {error_msg}"))
          if not candidates:
            del self.pending_responses[last_addr]
        return

    # Determine the key for pending_responses.
    # For track/device/parameter gets, we often include the indices in the response.
    # AbletonOSC usually returns [index, value] or [track_index, device_index, value] etc.
    # We try to match by address first.

    print(f"[DEBUG] Processing address: {address}, Args: {args}")
    if address in self.pending_responses:
      candidates = self.pending_responses[address]
      print(f"[DEBUG] Found {len(candidates)} candidates for {address}")
      # Find the best matching future based on arguments (e.g. track/device index)
      self._match_and_set_result(address, args, candidates)
      if not candidates:
        del self.pending_responses[address]
      return

    # Check for wildcard matches (if pending address ends with *)
    for pending_addr, candidates in self.pending_responses.items():
        if pending_addr.endswith("*"):
            # Check if address matches wildcard (e.g. /live/clip/get/name matches /live/clip/get/*)
            base_addr = pending_addr[:-1]
            if address.startswith(base_addr):
                print(f"[DEBUG] Wildcard match found: {address} matches {pending_addr}")
                # For wildcards, we might get MULTIPLE responses.
                # However, our JSON-RPC expects ONE response per ID.
                # Usually wildcard responses are sent as multiple OSC messages.
                # AbletonOSC might send them all or just one.
                # If we use a Future, we can only set it once.
                # Let's try to match indices to be sure.
                self._match_and_set_result(pending_addr, args, candidates)
                if not candidates:
                    del self.pending_responses[pending_addr]
                return

  def _match_and_set_result(self, address: str, args: list, candidates: list):
    """Internal helper to match arguments and set future results."""
    for i, (future, req_args) in enumerate(candidates):
        is_match = True
        if req_args is not None and len(req_args) > 0:
            should_echo = address.startswith(('/live/track/get', '/live/device/get', '/live/clip/get', '/live/clip_slot/get'))

            if should_echo:
                num_to_match = len(req_args)
                if "parameters/" in address and num_to_match > 2:
                    num_to_match = 2
                
                for j in range(num_to_match):
                    if j >= len(args):
                        is_match = False
                        break
                    
                    req_arg = req_args[j]
                    got_arg = args[j]
                    if isinstance(req_arg, (int, float)) and isinstance(got_arg, (int, float)):
                        if abs(float(req_arg) - float(got_arg)) > 0.0001:
                            is_match = False
                            break
                    elif req_arg != got_arg and str(req_arg) != str(got_arg):
                        if req_arg is None and got_arg == "":
                            continue
                        is_match = False
                        break

        if is_match and not future.done():
            print(f"[DEBUG] Match found for {address} with args {req_args}")
            future.set_result({
                'status': 'success',
                'address': address,
                'data': args
            })
            candidates.pop(i)
            return

  async def start(self):
    """Start both the socket server and OSC server."""
    # Start OSC server to receive Ableton messages
    loop = asyncio.get_event_loop()
    self.osc_server = AsyncIOOSCUDPServer(
      (self.socket_host, self.receive_port),
      self.dispatcher,
      loop
    )
    await self.osc_server.create_serve_endpoint()

    # Start socket server for MCP communication
    server = await asyncio.start_server(
      self.handle_socket_client,
      self.socket_host,
      self.socket_port
    )
    print(f"Ableton OSC Daemon listening on {self.socket_host}:{self.socket_port}")
    print(f"OSC Server receiving on {self.socket_host}:{self.receive_port}")
    print(f"Sending to Ableton on {self.ableton_host}:{self.ableton_port}")

    async with server:
      await server.serve_forever()

  async def handle_socket_client(self, reader, writer):
    """Handle incoming socket connections from MCP server."""
    client_address = writer.get_extra_info('peername')
    print(f"[NEW CONNECTION] Client connected from {client_address}")

    buffer = ""
    decoder = json.JSONDecoder()

    try:
      while True:
        data = await reader.read(4096)
        if not data:
          break

        buffer += data.decode()
        while buffer.strip():
          try:
            buffer = buffer.lstrip()
            if not buffer:
              break
            message, index = decoder.raw_decode(buffer)
            buffer = buffer[index:].lstrip()

            # Process the message
            await self.process_client_message(message, writer, client_address)

          except json.JSONDecodeError:
            # Wait for more data
            break

    except ConnectionError:
      # Client disconnected unexpectedly during data reading or message processing
      pass
    except Exception as e:
      print(f"[CONNECTION ERROR] Error handling client: {e}")
    finally:
      try:
        writer.close()
        await writer.wait_closed()
      except (ConnectionError, BrokenPipeError):
        # Ignore errors during closing if connection is already broken
        pass
      print(f"[CONNECTION CLOSED] Client {client_address} disconnected")

  async def process_client_message(self, message, writer, client_address):
    """Process a single JSON-RPC message from the client."""
    try:
      print(f"[RECEIVED MESSAGE] From {client_address}: {message}")

      # Support both old format (command) and new JSON-RPC format (method/params)
      request_id = message.get("id")
      command = message.get("command") or message.get("method")

      params = message.get("params", {})
      address = message.get("address") or params.get("address")
      args = message.get("args", params.get("args", []))

      if command == 'send_message':
        # Determine if we expect a response based on the OSC address
        # AbletonOSC usually only sends responses for /get/ queries and /live/test
        expect_response = address and (
            "/get/" in address or 
            address == "/live/test" or 
            address == "/live/api/get/log_level"
        )

        if address and address.startswith('/live/') and expect_response:
          # Create response future with timeout
          future = asyncio.Future()
          if address not in self.pending_responses:
            self.pending_responses[address] = []
          self.pending_responses[address].append((future, args))

          # Send to Ableton
          self.osc_client.send_message(address, args)

          try:
            # Wait for response with timeout
            response_data = await asyncio.wait_for(future, timeout=5.0)
            print(f"[OSC RESPONSE] Received: {response_data}")

            # Format as JSON-RPC response
            response = {
              "jsonrpc": "2.0",
              "id": request_id,
              "result": response_data
            }
            writer.write((json.dumps(response) + "\n").encode())
          except asyncio.TimeoutError:
            # Clean up future from list if it timed out
            if address in self.pending_responses:
              # Search and remove by future object
              for i, (f, _) in enumerate(self.pending_responses[address]):
                if f == future:
                  self.pending_responses[address].pop(i)
                  break
              if not self.pending_responses[address]:
                del self.pending_responses[address]

            error_response = {
              "jsonrpc": "2.0",
              "id": request_id,
              "error": {
                "code": -32000,
                "message": f"Timeout waiting for response to {address}"
              }
            }
            print(f"[OSC TIMEOUT] {error_response}")
            writer.write((json.dumps(error_response) + "\n").encode())
          except Exception as e:
            # Handle errors from AbletonOSC (e.g. unknown address)
            if address in self.pending_responses:
              for i, (f, _) in enumerate(self.pending_responses[address]):
                if f == future:
                  self.pending_responses[address].pop(i)
                  break
              if not self.pending_responses[address]:
                del self.pending_responses[address]

            error_response = {
              "jsonrpc": "2.0",
              "id": request_id,
              "error": {
                "code": -32001,
                "message": str(e)
              }
            }
            print(f"[OSC ERROR] {error_response}")
            writer.write((json.dumps(error_response) + "\n").encode())

        elif address:
          # For commands that don't expect responses
          self.osc_client.send_message(address, args)
          response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"status": "sent"}
          }
          writer.write((json.dumps(response) + "\n").encode())
        else:
          error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
              "code": -32602,
              "message": "Missing OSC address"
            }
          }
          writer.write((json.dumps(error_response) + "\n").encode())

      elif command == 'send_bundle':
        messages = message.get("messages", params.get("messages", []))
        if not messages:
          error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
              "code": -32602,
              "message": "Missing messages for bundle"
            }
          }
          writer.write((json.dumps(error_response) + "\n").encode())
          return

        bundle_builder = OscBundleBuilder(0)  # 0 means immediately
        futures_to_wait = []

        for msg_data in messages:
          addr = msg_data.get("address")
          msg_args = msg_data.get("args", [])
          
          osc_msg = OscMessageBuilder(address=addr)
          for arg in msg_args:
            osc_msg.add_arg(arg)
          bundle_builder.add_content(osc_msg.build())

          # Determine if we expect a response
          expect_response = addr and (
              "/get/" in addr or 
              addr == "/live/test" or 
              addr == "/live/api/get/log_level"
          )

          if expect_response:
            future = asyncio.Future()
            if addr not in self.pending_responses:
              self.pending_responses[addr] = []
            self.pending_responses[addr].append((future, msg_args))
            futures_to_wait.append((future, addr, msg_args))

        # Send the bundle
        self.osc_client.send(bundle_builder.build())

        if not futures_to_wait:
          response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"status": "bundle_sent"}
          }
          writer.write((json.dumps(response) + "\n").encode())
          return

        # Wait for all expected responses
        try:
          # We wait for all futures with a global timeout
          results = []
          for future, addr, msg_args in futures_to_wait:
            try:
              res = await asyncio.wait_for(future, timeout=5.0)
              results.append({"address": addr, "args": msg_args, "result": res, "ok": True})
            except asyncio.TimeoutError:
              results.append({"address": addr, "args": msg_args, "error": "timeout", "ok": False})
              # Clean up
              if addr in self.pending_responses:
                for i, (f, _) in enumerate(self.pending_responses[addr]):
                  if f == future:
                    self.pending_responses[addr].pop(i)
                    break
          
          response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": results
          }
          writer.write((json.dumps(response) + "\n").encode())
        except Exception as e:
          error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
              "code": -32002,
              "message": f"Bundle execution error: {str(e)}"
            }
          }
          writer.write((json.dumps(error_response) + "\n").encode())

      elif command == 'get_status':
        result = {
          'status': 'ok',
          'ableton_port': self.ableton_port,
          'receive_port': self.receive_port
        }
        response = {
          "jsonrpc": "2.0",
          "id": request_id,
          "result": result
        }
        print(f"[STATUS REQUEST] Responding with: {response}")
        writer.write((json.dumps(response) + "\n").encode())
      else:
        error_response = {
          "jsonrpc": "2.0",
          "id": request_id,
          "error": {
            "code": -32601,
            "message": "Unknown command"
          }
        }
        print(f"[UNKNOWN COMMAND] Received: {message}")
        writer.write((json.dumps(error_response) + "\n").encode())

      await writer.drain()

    except Exception as e:
      # If connection is broken, re-raise to let handle_socket_client handle it
      if isinstance(e, ConnectionError):
        raise
      print(f"[MESSAGE PROCESSING ERROR] {e}")
      error_response = {
        "jsonrpc": "2.0",
        "error": {
          "code": -32603,
          "message": f"Internal error: {str(e)}"
        }
      }
      try:
        writer.write((json.dumps(error_response) + "\n").encode())
        await writer.drain()
      except Exception:
        pass


if __name__ == "__main__":
  daemon = AbletonOSCDaemon()
  try:
    asyncio.run(daemon.start())
  except OSError as e:
    if e.errno == errno.EADDRINUSE:
      print("\n" + "!" * 80)
      print(f"ERROR: Port already in use. An application is already running on port {daemon.socket_port} or {daemon.receive_port}.")
      print("To find out which process is using the port, run:")
      print(f"lsof -i :{daemon.socket_port}")
      print(f"lsof -i :{daemon.receive_port}")
      print("\nTo see the full script path of the running process, run:")
      print(f"ps -wwfp $(lsof -t -i :{daemon.socket_port})")
      print(f"ps -wwfp $(lsof -t -i :{daemon.receive_port})")
      print("\nIf you want to kill the running osc_daemon.py, execute the following in the terminal:")
      print('pkill -f "python.*osc_daemon.py" || true')
      print("!" * 80 + "\n")
      sys.exit(1)
    raise e
