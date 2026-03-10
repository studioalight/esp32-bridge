#!/usr/bin/env python3
"""
ESP32 Bridge Terminal Monitor - with echo toggle

Usage:
    python3 monitor.py                    # Connect and monitor
    python3 monitor.py --duration 30      # Monitor for 30 seconds

Keys:
    'e' - Toggle local echo on/off
    'r' - Send reset command
    'b' - Send bootloader command
    's' - Show status
    'q' - Quit
"""

import asyncio
import websockets
import json
import ssl
import sys
import select
import termios
import tty
import os

WSS_URI = "wss://esp32-bridge.tailbdd5a.ts.net:5678"
ECHO_HELP = """
[Keys]
  e - Toggle echo
  r - Reset
  b - Bootloader
  s - Status
  q - Quit
"""


def setup_terminal():
    """Set terminal to raw mode for key detection"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
    except:
        pass
    return old_settings


def restore_terminal(old_settings):
    """Restore terminal settings"""
    fd = sys.stdin.fileno()
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def check_key():
    """Check if key pressed without blocking"""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None


async def monitor():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    print("ESP32 Bridge Terminal Monitor")
    print(f"Connecting to {WSS_URI}...")
    print(ECHO_HELP)
    
    echo_enabled = True
    
    try:
        # Set up terminal for key detection
        old_settings = setup_terminal()
        
        async with websockets.connect(WSS_URI, ssl=ssl_context, ping_interval=None) as ws:
            print("\nConnected! Press 'e' to toggle echo, 'q' to quit\n")
            
            while True:
                # Check for key press
                key = check_key()
                if key:
                    if key == 'e' or key == 'E':
                        echo_enabled = not echo_enabled
                        status = "enabled" if echo_enabled else "disabled"
                        print(f"\n[INFO] Echo {status}")
                    elif key == 'r' or key == 'R':
                        print("\n[INFO] Sending reset...")
                        await ws.send(json.dumps({'action': 'reset'}))
                    elif key == 'b' or key == 'B':
                        print("\n[INFO] Sending bootloader...")
                        await ws.send(json.dumps({'action': 'bootloader'}))
                    elif key == 's' or key == 'S':
                        print("\n[INFO] Requesting status...")
                        await ws.send(json.dumps({'action': 'status'}))
                    elif key == 'q' or key == 'Q':
                        print("\n[INFO] Quitting...")
                        break
                    elif key == '\x03':  # Ctrl+C
                        print("\n[INFO] Interrupted")
                        break
                
                # Check for WebSocket messages
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.01)
                    try:
                        data = json.loads(msg)
                        if data.get('type') == 'serial':
                            text = data.get('text', '')
                            if echo_enabled:
                                print(text, end='')
                        elif data.get('type') == 'system':
                            print(f"\n[SYS] {data.get('message', '')}")
                        elif data.get('type') == 'status':
                            print(f"\n[STATUS] Port: {data.get('port', 'none')}")
                            print(f"[STATUS] Connected: {data.get('connected')}")
                            print(f"[STATUS] Baud: {data.get('baudrate')}")
                            print(f"[STATUS] Chip: {data.get('chip', 'unknown')}")
                    except json.JSONDecodeError:
                        if echo_enabled:
                            print(msg, end='')
                except asyncio.TimeoutError:
                    pass
                    
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted")
    finally:
        restore_terminal(old_settings)
        print("\n[INFO] Disconnected")


if __name__ == '__main__':
    asyncio.run(monitor())
