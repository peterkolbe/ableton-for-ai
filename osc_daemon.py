# osc_daemon.py
import asyncio
import json
from typing import Dict

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


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
      for i, (future, req_args) in enumerate(candidates):
        is_match = True
        if req_args is not None and len(req_args) > 0:
          # AbletonOSC usually returns the input arguments as a prefix in the response
          # EXCEPT for some addresses that don't echo arguments (e.g. /live/song/get/tempo)
          # We check if the address is one that SHOULD echo arguments
          should_echo = address.startswith(('/live/track/get', '/live/device/get', '/live/clip/get', '/live/clip_slot/get'))

          if should_echo:
            for j, req_arg in enumerate(req_args):
              # Relax matching: try to match as strings if types differ
              if j >= len(args) or (req_arg != args[j] and str(req_arg) != str(args[j])):
                # Special case: allow empty strings to match None if returned by Ableton
                if req_arg is None and j < len(args) and args[j] == "":
                  continue
                print(
                  f"[DEBUG] Arg mismatch at index {j}: req={req_arg} ({type(req_arg)}), got={args[j] if j < len(args) else 'MISSING'} ({type(args[j]) if j < len(args) else 'N/A'})")
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
          if not candidates:
            del self.pending_responses[address]
          return
      print(f"[DEBUG] No match found for {address} with args {args} among {len(candidates)} candidates")

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

    except Exception as e:
      print(f"[CONNECTION ERROR] Error handling client: {e}")
    finally:
      writer.close()
      await writer.wait_closed()
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
        # For commands that expect responses, set up a future
        if address and address.startswith(
            ('/live/device/get', '/live/scene/get', '/live/view/get', '/live/clip/get', '/live/clip_slot/get', '/live/track/get',
             '/live/song/get', '/live/api/get', '/live/application/get', '/live/test', '/live/error')):
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
      except:
        pass


if __name__ == "__main__":
  daemon = AbletonOSCDaemon()
  asyncio.run(daemon.start())
