#!/usr/bin/env python3
"""
ESP32 Bridge v2.0 - Serial monitor + firmware flashing via WebSocket

Hardware: ESP32-P4, ESP32-S3, ESP32 (auto-detected)
Requirements: esptool.py v4.4+ for ESP32-P4 support

Features:
    - Auto-detect ESP32 port with hotplug support (recovery after unplug)
    - Configurable baud rate (default 460800)
    - CLI arguments and config file for persistence
    - Live serial monitoring streamed via WebSocket
    - Remote reset/bootloader control
    - HTTP firmware file upload
    - esptool.py integration for flashing
    - Flash progress streamed to WebSocket clients

Usage:
    python3 esp32-bridge.py --auto                    # Auto-detect and run
    python3 esp32-bridge.py --port /dev/cu.usbmodem   # Specific port
    python3 esp32-bridge.py --baud 921600             # Custom baud rate
    python3 esp32-bridge.py --config ~/bridge.yaml    # Use config file

WebSocket Commands:
    {"action": "reset"}                       # Reset ESP32
    {"action": "bootloader"}                   # Enter bootloader
    {"action": "status"}                       # Get status
    {"action": "flash", "file": "firmware.bin", "addr": "0x10000"}
    {"action": "set_baud", "rate": 460800}   # Change baud rate
    {"action": "get_chip"}                   # Get current chip type
    {"action": "set_chip", "chip": "esp32p4"} # Set chip type (auto-detected)

Supported chips:
    esp32, esp32s2, esp32s3, esp32c3, esp32c6, esp32h2, esp32p4

HTTP Endpoints:
    POST /upload         - Upload firmware file
    GET  /files          - List uploaded files
    GET  /               - Web UI

Requires:
    pip install pyserial websockets aiohttp pyyaml
    pip install esptool
"""

import asyncio
import serial
import serial.tools.list_ports
import websockets
import sys
import argparse
import json
import time
import os
import subprocess
import yaml
from datetime import datetime
from pathlib import Path
from aiohttp import web

# Default configuration
DEFAULT_CONFIG = {
    'serial': {
        'port': None,  # Auto-detect
        'baudrate': 460800,
        'timeout': 0.1,
        'reconnect_delay': 1.0,
        'max_reconnect_delay': 30.0,
        'hotplug_check_interval': 2.0,
    },
    'network': {
        'http_host': '0.0.0.0',
        'http_port': 5679,
        'ws_port': 5678,
        'use_tailscale': True,
    },
    'uploads': {
        'directory': '~/.esp32-bridge/uploads',
        'max_size_mb': 10,
    },
    'flash': {
        'default_chip': 'esp32p4',
        'default_baudrate': 460800,
    },
    'logging': {
        'level': 'INFO',
        'timestamp_format': '%H:%M:%S',
    }
}

# Global state
STATE = {
    'config': {},
    'connected': False,
    'port': None,
    'baudrate': 460800,
    'chip': 'esp32p4',
    'bytes_received': 0,
    'lines_received': 0,
    'last_activity': None,
    'reconnect_count': 0,
    'start_time': time.time(),
    'flashing': False,
    'flash_progress': 0,
    'tailscale_ip': None,
    'http_endpoint': None,
}

clients = set()
serial_conn = None
config_path = None

# ESP32 USB identifiers
ESP32_KEYWORDS = [
    ('usb jtag/serial debug', 'ESP32-S3 USB JTAG'),
    ('esp32-p4', 'ESP32-P4'),
    ('jtag', 'JTAG'),
    ('cp210', 'CP210x'),
    ('ch340', 'CH340'),
    ('ch9102', 'CH9102'),
    ('ft232', 'FT232'),
    ('usb-serial', 'USB-Serial'),
    ('silicon labs', 'Silicon Labs'),
    ('wch.cn', 'WCH USB'),
]


def load_config(path=None):
    """Load config from file or create default"""
    global STATE
    
    # Start with defaults
    config = DEFAULT_CONFIG.copy()
    
    # Try to load from file
    if path and Path(path).exists():
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
            # Merge with defaults
            for section, values in user_config.items():
                if section in config:
                    config[section].update(values)
    
    # Expand paths
    config['uploads']['directory'] = os.path.expanduser(config['uploads']['directory'])
    os.makedirs(config['uploads']['directory'], exist_ok=True)
    
    STATE['config'] = config
    return config


def save_config(path, config):
    """Save config to file"""
    with open(path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    log(f"Config saved to: {path}", 'CONFIG')


def get_tailscale_ip():
    """Detect Tailscale IP address (100.x.x.x)"""
    tailscale_paths = [
        '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
        'tailscale'
    ]
    
    for cmd in tailscale_paths:
        try:
            result = subprocess.run([cmd, 'ip', '-4'], 
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ip = result.stdout.strip().split('\n')[0]
                if ip.startswith('100.'):
                    return ip
        except:
            continue
    
    return None


def log(msg, level='INFO'):
    """Print with timestamp"""
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] [{level}] {msg}")
    sys.stdout.flush()


def get_esp32_port(preferred_port=None):
    """Auto-detect ESP32 USB port with fallback"""
    ports = list(serial.tools.list_ports.comports())
    
    if not ports:
        return None
    
    # Try preferred port first
    if preferred_port:
        for port in ports:
            if port.device == preferred_port:
                return port.device
    
    # Try ESP32 keywords
    for keyword, name in ESP32_KEYWORDS:
        for port in ports:
            check = port.description.lower() + ' ' + port.device.lower()
            if keyword in check:
                log(f"Found {name} on {port.device}")
                return port.device
    
    # Fallback to any USB port
    usb_ports = [p for p in ports if 'usb' in p.device.lower()]
    if usb_ports:
        return usb_ports[0].device
    
    return ports[0].device


def reset_esp32(port, baudrate):
    """Reset ESP32 using DTR/RTS"""
    try:
        log(f"Resetting ESP32 on {port}...", 'RESET')
        with serial.Serial(port, baudrate, timeout=1) as ser:
            ser.dtr = True
            ser.rts = False
            time.sleep(0.05)
            ser.rts = True
            time.sleep(0.05)
        log("Reset complete", 'RESET')
        return True
    except Exception as e:
        log(f"Reset failed: {e}", 'ERROR')
        return False


def enter_bootloader(port, baudrate):
    """Enter bootloader mode"""
    try:
        log(f"Entering bootloader on {port}...", 'BOOT')
        with serial.Serial(port, baudrate, timeout=1) as ser:
            ser.dtr = False
            ser.rts = True
            time.sleep(0.1)
            ser.rts = False
            time.sleep(0.1)
            ser.rts = True
            time.sleep(0.5)
            ser.dtr = True
        log("Bootloader mode active", 'BOOT')
        return True
    except Exception as e:
        log(f"Bootloader failed: {e}", 'ERROR')
        return False


async def broadcast(msg):
    """Send message to all WebSocket clients"""
    if clients:
        dead = set()
        for client in clients:
            try:
                await client.send(msg)
            except:
                dead.add(client)
        for client in dead:
            clients.discard(client)


async def flash_firmware(filepath, address, port, baudrate, chip='esp32p4'):
    """Flash firmware using esptool.py"""
    global STATE, serial_conn
    
    if not os.path.exists(filepath):
        await broadcast(json.dumps({
            'type': 'flash', 'status': 'error', 
            'msg': f'File not found: {filepath}'
        }))
        return False
    
    # Close serial connection for flashing
    if serial_conn and serial_conn.is_open:
        serial_conn.close()
        await asyncio.sleep(0.5)
    
    STATE['flashing'] = True
    STATE['flash_progress'] = 0
    
    await broadcast(json.dumps({
        'type': 'flash', 'status': 'start',
        'file': os.path.basename(filepath), 'addr': address
    }))
    
    try:
        cmd = [
            'esptool.py',
            '--chip', chip,
            '--port', port,
            '--baud', str(baudrate),
            '--before', 'default_reset',
            '--after', 'hard_reset',
            'write_flash', '-z',
            '--flash_mode', 'dio',
            '--flash_freq', '80m',
            '--flash_size', 'detect',
            address, filepath
        ]
        
        log(f"Starting flash: esptool.py --chip {chip} --port {port} --baud {baudrate}...", 'FLASH')
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            text = line.decode().strip()
            log(f"[esptool] {text[:100]}")
            
            # Parse progress
            if '%' in text:
                try:
                    pct_str = text.split('%')[0].split()[-1]
                    pct = int(pct_str)
                    STATE['flash_progress'] = pct
                    await broadcast(json.dumps({
                        'type': 'flash', 'status': 'progress',
                        'pct': pct, 'line': text
                    }))
                except:
                    pass
            else:
                await broadcast(json.dumps({
                    'type': 'flash', 'status': 'output', 'line': text
                }))
        
        returncode = await process.wait()
        
        if returncode == 0:
            log("Flash complete!", 'FLASH')
            await broadcast(json.dumps({'type': 'flash', 'status': 'complete'}))
            return True
        else:
            log(f"Flash failed: code {returncode}", 'ERROR')
            await broadcast(json.dumps({
                'type': 'flash', 'status': 'error', 'code': returncode
            }))
            return False
            
    except Exception as e:
        log(f"Flash error: {e}", 'ERROR')
        await broadcast(json.dumps({
            'type': 'flash', 'status': 'error', 'msg': str(e)
        }))
        return False
    finally:
        STATE['flashing'] = False
        STATE['flash_progress'] = 0


async def monitor_hotplug(config):
    """Monitor for USB hotplug events"""
    global STATE
    
    known_ports = set()
    check_interval = config['serial']['hotplug_check_interval']
    
    while True:
        await asyncio.sleep(check_interval)
        
        try:
            current_ports = set(p.device for p in serial.tools.list_ports.comports())
            
            # New port connected
            new_ports = current_ports - known_ports
            if new_ports and not STATE['connected']:
                log(f"New USB device detected: {new_ports}", 'HOTPLUG')
                # Trigger reconnect
                if serial_conn:
                    try:
                        serial_conn.close()
                    except:
                        pass
            
            # Port disconnected
            gone_ports = known_ports - current_ports
            if gone_ports and STATE['connected']:
                log(f"USB device disconnected: {gone_ports}", 'HOTPLUG')
                if serial_conn:
                    try:
                        serial_conn.close()
                    except:
                        pass
            
            known_ports = current_ports
            
        except Exception as e:
            log(f"Hotplug monitor error: {e}", 'ERROR')


async def read_serial(config):
    """Read serial data with enhanced reconnection"""
    global serial_conn, STATE
    
    buffer = ""
    preferred_port = config['serial']['port']
    baudrate = config['serial']['baudrate']
    timeout = config['serial']['timeout']
    reconnect_delay = config['serial']['reconnect_delay']
    max_reconnect_delay = config['serial']['max_reconnect_delay']
    
    while True:
        try:
            if STATE['flashing']:
                await asyncio.sleep(0.5)
                continue
            
            port = get_esp32_port(preferred_port)
            if not port:
                log("No ESP32 device found", 'CONNECT')
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)
                continue
            
            log(f"Opening {port} @ {baudrate}...", 'CONNECT')
            serial_conn = serial.Serial(port, baudrate, timeout=timeout)
            serial_conn.rts = True
            serial_conn.dtr = True
            
            STATE['connected'] = True
            STATE['port'] = port
            STATE['baudrate'] = baudrate
            STATE['reconnect_count'] = 0
            
            log("Serial connected!", 'CONNECTED')
            await broadcast(json.dumps({
                'type': 'system',
                'message': f"Serial connected: {port} @ {baudrate}"
            }))
            
            reconnect_delay = config['serial']['reconnect_delay']
            
            while serial_conn and serial_conn.is_open:
                if STATE['flashing']:
                    serial_conn.close()
                    break
                
                try:
                    if serial_conn.in_waiting:
                        data = serial_conn.read(serial_conn.in_waiting)
                        text = data.decode('utf-8', errors='replace')
                        buffer += text
                        
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.rstrip('\r')
                            if line:
                                STATE['lines_received'] += 1
                                STATE['bytes_received'] += len(line)
                                STATE['last_activity'] = time.time()
                                await broadcast(line)
                    
                    await asyncio.sleep(0.01)
                    
                except serial.SerialException:
                    break
                except Exception as e:
                    log(f"Read error: {e}", 'ERROR')
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            log(f"Cannot open port: {e}", 'ERROR')
        
        if serial_conn:
            try:
                serial_conn.close()
            except:
                pass
            serial_conn = None
        
        STATE['connected'] = False
        STATE['reconnect_count'] += 1
        
        log(f"Disconnected. Reconnecting in {reconnect_delay}s...", 'RECONNECT')
        await broadcast(json.dumps({
            'type': 'system',
            'message': f"Disconnected - reconnecting in {reconnect_delay}s"
        }))
        
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)


async def handle_ws(websocket):
    """Handle WebSocket connections"""
    global STATE
    clients.add(websocket)
    
    log(f"Client connected: {websocket.remote_address}", 'WS')
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get('action')
                config = STATE['config']
                port = STATE['port'] or config['serial']['port']
                baudrate = data.get('rate', STATE['baudrate'] or config['serial']['baudrate'])
                
                if action == 'reset':
                    if port:
                        reset_esp32(port, baudrate)
                        await websocket.send(json.dumps({'type': 'system', 'message': 'Reset triggered'}))
                    else:
                        await websocket.send(json.dumps({'type': 'error', 'message': 'No port'}))
                
                elif action == 'bootloader':
                    if port:
                        enter_bootloader(port, baudrate)
                        await websocket.send(json.dumps({'type': 'system', 'message': 'Bootloader mode'}))
                    else:
                        await websocket.send(json.dumps({'type': 'error', 'message': 'No port'}))
                
                elif action == 'flash':
                    filename = data.get('file')
                    address = data.get('addr', '0x10000')
                    chip = data.get('chip', STATE['chip'])
                    
                    if not filename:
                        await websocket.send(json.dumps({'type': 'error', 'message': 'No file specified'}))
                        continue
                    
                    filepath = os.path.join(config['uploads']['directory'], filename)
                    if not os.path.exists(filepath):
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': f'File not found: {filename}'
                        }))
                        continue
                    
                    await websocket.send(json.dumps({
                        'type': 'system',
                        'message': f"Flashing {filename} to {address} (chip: {chip})"
                    }))
                    
                    if port and not port.startswith('/dev/tty'):
                        await flash_firmware(filepath, address, port, baudrate, chip)
                    else:
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': 'Cannot flash: no valid port'
                        }))
                
                elif action == 'status':
                    await websocket.send(json.dumps({
                        'type': 'status',
                        'connected': STATE['connected'],
                        'port': STATE['port'],
                        'baudrate': STATE['baudrate'],
                        'chip': STATE['chip'],
                        'bytes_received': STATE['bytes_received'],
                        'lines_received': STATE['lines_received']
                    }))
                
                elif action == 'set_baud':
                    new_baud = data.get('rate')
                    if new_baud:
                        STATE['baudrate'] = new_baud
                        config['serial']['baudrate'] = new_baud
                        if config_path:
                            save_config(config_path, config)
                        await websocket.send(json.dumps({
                            'type': 'system',
                            'message': f"Baud rate changed to {new_baud}"
                        }))
                
                elif action == 'get_config':
                    await websocket.send(json.dumps({
                        'type': 'config',
                        'config': config
                    }))
                
                elif action == 'get_chip':
                    await websocket.send(json.dumps({
                        'type': 'chip',
                        'chip': STATE['chip'],
                        'supported': ['esp32', 'esp32s2', 'esp32s3', 'esp32c3', 'esp32c6', 'esp32h2', 'esp32p4']
                    }))
                
                elif action == 'set_chip':
                    new_chip = data.get('chip')
                    supported = ['esp32', 'esp32s2', 'esp32s3', 'esp32c3', 'esp32c6', 'esp32h2', 'esp32p4']
                    if new_chip and new_chip in supported:
                        STATE['chip'] = new_chip
                        config['flash']['default_chip'] = new_chip
                        if config_path:
                            save_config(config_path, config)
                        log(f"Chip set to: {new_chip}", 'CONFIG')
                        await websocket.send(json.dumps({
                            'type': 'system',
                            'message': f"Chip changed to {new_chip}"
                        }))
                    else:
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': f"Invalid chip. Supported: {', '.join(supported)}"
                        }))
                
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': f"Unknown action: {action}"
                    }))
                    
            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'Invalid JSON'
                }))
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.discard(websocket)
        log(f"Client disconnected: {websocket.remote_address}", 'WS')


# HTTP handlers
async def handle_upload(request):
    """Handle firmware upload"""
    config = STATE['config']
    upload_dir = config['uploads']['directory']
    max_size = config['uploads']['max_size_mb'] * 1024 * 1024
    
    reader = await request.multipart()
    field = await reader.next()
    
    if field.name != 'file':
        return web.json_response({'error': 'Expected file field'}, status=400)
    
    filename = field.filename
    if not filename:
        return web.json_response({'error': 'No filename'}, status=400)
    
    if '..' in filename or '/' in filename:
        return web.json_response({'error': 'Invalid filename'}, status=400)
    
    filepath = os.path.join(upload_dir, filename)
    
    # Read and write file
    size = 0
    with open(filepath, 'wb') as f:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > max_size:
                os.unlink(filepath)
                return web.json_response({'error': 'File too large'}, status=400)
            f.write(chunk)
    
    log(f"Uploaded: {filename} ({size:,} bytes)", 'UPLOAD')
    
    return web.json_response({
        'success': True,
        'filename': filename,
        'size': size,
        'path': filepath
    })


async def handle_files(request):
    """List uploaded files"""
    config = STATE['config']
    upload_dir = config['uploads']['directory']
    
    files = []
    for f in os.listdir(upload_dir):
        filepath = os.path.join(upload_dir, f)
        files.append({
            'name': f,
            'size': os.path.getsize(filepath),
            'modified': os.path.getmtime(filepath)
        })
    
    return web.json_response({'files': files})


async def handle_index(request):
    """Serve web UI"""
    # Get actual host from request or use configured tailscale IP
    host = request.headers.get('Host', '').split(':')[0]
    if not host and STATE['tailscale_ip']:
        host = STATE['tailscale_ip']
    if not host:
        host = 'localhost'
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ESP32 Bridge</title>
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1a1a2e; color: #fff; }}
        #terminal {{ background: #0f0f1a; padding: 15px; height: 400px; overflow-y: auto; 
                     border-radius: 5px; font-size: 13px; white-space: pre-wrap; }}
        .connected {{ color: #24e08a; }}
        .disconnected {{ color: #ff5c5c; }}
        button {{ background: #e94560; border: none; color: white; 
                  padding: 10px 20px; margin: 5px; border-radius: 5px; cursor: pointer; }}
        input {{ padding: 10px; margin: 5px; }}
    </style>
</head>
<body>
    <h1>🔌 ESP32 Bridge v2.0</h1>
    <div id="status">Connecting...</div>
    <div>
        <button onclick="sendCmd('reset')">Reset</button>
        <button onclick="sendCmd('bootloader')">Bootloader</button>
        <button onclick="sendCmd('status')">Status</button>
        <button onclick="document.getElementById('terminal').innerHTML=''">Clear</button>
    </div>
    <div>
        <select id="baud">
            <option value="115200">115200</option>
            <option value="230400">230400</option>
            <option value="460800" selected>460800</option>
            <option value="921600">921600</option>
        </select>
        <button onclick="setBaud()">Set Baud</button>
    </div>
    <div id="terminal"></div>
    <script>
        // Server-injected host: {host}
        // Using ws:// since we're on Tailscale (encrypted mesh)
        const wsHost = window.location.hostname || '{host}';
        const wsUrl = 'ws://' + wsHost + ':5678/ws';
        console.log('WebSocket URL:', wsUrl);
        const ws = new WebSocket(wsUrl);
        const terminal = document.getElementById('terminal');
        const status = document.getElementById('status');
        
        ws.onopen = () => {{ status.innerHTML = '<span class="connected">● Connected</span>'; }};
        ws.onclose = () => {{ status.innerHTML = '<span class="disconnected">● Disconnected</span>'; }};
        
        ws.onmessage = (e) => {{
            try {{
                const data = JSON.parse(e.data);
                if (data.type === 'serial') {{
                    appendLine(data.text || '');
                }} else if (data.type === 'system') {{
                    appendLine('[SYS] ' + data.message);
                }} else if (data.type === 'flash') {{
                    if (data.status === 'progress') {{
                        appendLine('[FLASH] ' + data.pct + '%');
                    }} else if (data.status === 'complete') {{
                        appendLine('[FLASH] ✓ Complete');
                    }}
                }}
            }} catch {{
                appendLine(e.data);
            }}
        }};
        
        function appendLine(text) {{
            const safeText = String(text).replace(/</g, '&lt;').replace(/>/g, '&gt;');
            terminal.innerHTML += safeText + '<br>';
            terminal.scrollTop = terminal.scrollHeight;
        }}
        
        function sendCmd(action) {{
            if (ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify({{action: action}}));
            }} else {{
                status.innerHTML = '<span class="disconnected">● WebSocket not connected</span>';
            }}
        }}
        
        function setBaud() {{
            const rate = document.getElementById('baud').value;
            if (ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify({{action: 'set_baud', rate: parseInt(rate)}}));
            }}
        }}
    </script>
</body>
</html>
"""
    return web.Response(text=html, content_type='text/html')


async def start_http(config):
    """Start HTTP server"""
    app = web.Application()
    
    app.router.add_post('/upload', handle_upload)
    app.router.add_get('/files', handle_files)
    app.router.add_get('/', handle_index)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    host = config['network']['http_host']
    port = config['network']['http_port']
    
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    log(f"HTTP server: http://{host}:{port}", 'HTTP')
    
    if config['network']['use_tailscale']:
        ts_ip = get_tailscale_ip()
        if ts_ip:
            STATE['tailscale_ip'] = ts_ip
            STATE['http_endpoint'] = f"https://{ts_ip}:{port}"
            log(f"Tailscale HTTPS: {STATE['http_endpoint']}", 'HTTP')
    
    return runner


async def main():
    """Main entry"""
    global config_path, STATE
    
    parser = argparse.ArgumentParser(description='ESP32 Bridge v2.0')
    parser.add_argument('--config', '-c', help='Config file path')
    parser.add_argument('--port', '-p', help='Serial port (auto-detect if not specified)')
    parser.add_argument('--baud', '-b', type=int, default=460800, help='Baud rate (default: 460800)')
    parser.add_argument('--chip', type=str, default='esp32p4', 
                       choices=['esp32', 'esp32s2', 'esp32s3', 'esp32c3', 'esp32c6', 'esp32h2', 'esp32p4'],
                       help='Default chip type (default: esp32p4)')
    parser.add_argument('--http-port', type=int, default=5679, help='HTTP port')
    parser.add_argument('--ws-port', type=int, default=5678, help='WebSocket port')
    parser.add_argument('--auto', action='store_true', help='Auto-detect and run')
    parser.add_argument('--save-config', help='Save current config to file')
    args = parser.parse_args()
    
    # Load config - check for default if not specified
    config_path = args.config
    if not config_path:
        default_config = os.path.expanduser('~/.esp32-bridge/config.yaml')
        if os.path.exists(default_config):
            config_path = default_config
            log(f"Using default config: {config_path}", 'CONFIG')
    
    config = load_config(config_path)
    
    # Override with CLI args
    if args.baud:
        config['serial']['baudrate'] = args.baud
    if args.port:
        config['serial']['port'] = args.port
    if args.chip:
        config['flash']['default_chip'] = args.chip
    if args.http_port:
        config['network']['http_port'] = args.http_port
    if args.ws_port:
        config['network']['ws_port'] = args.ws_port
    
    STATE['baudrate'] = config['serial']['baudrate']
    STATE['chip'] = config['flash']['default_chip']
    
    # Save config if requested
    if args.save_config:
        save_config(os.path.expanduser(args.save_config), config)
    
    log(f"ESP32 Bridge v2.0 starting...", 'START')
    log(f"Baud rate: {config['serial']['baudrate']}", 'CONFIG')
    log(f"Default chip: {config['flash']['default_chip']}", 'CONFIG')
    log(f"Upload dir: {config['uploads']['directory']}", 'CONFIG')
    
    # Start services
    http_runner = await start_http(config)
    
    # Start serial reader
    serial_task = asyncio.create_task(read_serial(config))
    
    # Start hotplug monitor
    hotplug_task = asyncio.create_task(monitor_hotplug(config))
    
    # Start WebSocket server
    ws_port = config['network']['ws_port']
    log(f"WebSocket server: ws://0.0.0.0:{ws_port}/ws", 'WS')
    
    async with websockets.serve(handle_ws, '0.0.0.0', ws_port):
        log("Bridge ready!", 'READY')
        
        # Keep running
        while True:
            await asyncio.sleep(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Stopped by user", 'STOP')
