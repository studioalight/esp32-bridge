# ESP32 Bridge v2.0

Network bridge for ESP32 development - serial monitor + firmware flashing over WebSocket.

## Features

- **Serial Monitoring** - Live streaming over WebSocket with auto-reconnect
- **USB Hotplug Support** - Detects unplugging/replugging automatically
- **Firmare Flashing** - via esptool.py with progress tracking
- **HTTP Upload** - Upload .bin files via curl
- **Baud Rate Selection** - CLI args and runtime switching
- **Config Persistence** - YAML config file support
- **Tailscale Integration** - Auto-discovers Tailscale IP
- **Web UI** - Browser-based serial monitor

## Quick Start

### Installation

```bash
pip install pyserial websockets aiohttp pyyaml esptool
```

### Run

```bash
# Auto-detect and run with defaults
python3 esp32-bridge.py --auto

# Specify baud rate
python3 esp32-bridge.py --baud 921600

# Specify port
python3 esp32-bridge.py --port /dev/cu.usbmodem101

# Use config file
python3 esp32-bridge.py --config ~/bridge.yaml

# Save current settings
python3 esp32-bridge.py --save-config ~/bridge.yaml --baud 460800
```

## Configuration

### Default Config (`~/.esp32-bridge/config.yaml`)

```yaml
serial:
  port: null              # Auto-detect
  baudrate: 460800        # Default baud
  timeout: 0.1
  reconnect_delay: 1.0
  max_reconnect_delay: 30.0
  hotplug_check_interval: 2.0

network:
  http_host: 0.0.0.0
  http_port: 5679
  ws_port: 5678
  use_tailscale: true

uploads:
  directory: ~/.esp32-bridge/uploads
  max_size_mb: 10

flash:
  default_chip: esp32p4
  default_baudrate: 460800

logging:
  level: INFO
```

## HTTP API

### Upload Binary

```bash
curl -k -F "file=@firmware.bin" https://100.x.x.x:5679/upload
```

Response:
```json
{
  "success": true,
  "filename": "firmware.bin",
  "size": 617296
}
```

### List Files

```bash
curl -k https://100.x.x.x:5679/files
```

## WebSocket Commands

Connect to `wss://HOST:5678/ws`

```json
// Reset ESP32
{"action": "reset"}

// Enter bootloader
{"action": "bootloader"}

// Flash file
{"action": "flash", "file": "firmware.bin", "addr": "0x10000"}

// Get status
{"action": "status"}

// Change baud rate
{"action": "set_baud", "rate": 921600}

// Get config
{"action": "get_config"}
```

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--auto` | - | Auto-detect and run |
| `--port` | auto | Serial port device |
| `--baud` | 460800 | Default baud rate |
| `--config` | - | Config file path |
| `--save-config` | - | Save config to file |
| `--http-port` | 5679 | HTTP server port |
| `--ws-port` | 5678 | WebSocket port |

## Baud Rates Supported

| Rate | Notes |
|------|-------|
| 115200 | Standard, reliable |
| 460800 | **Default, recommended** |
| 921600 | Fast flash, may be unstable |

## Recovery Features

### Cable Unplug Detection

The bridge automatically:
1. Detects USB disconnection
2. Waits configured delay
3. Scans for new device
4. Reconnects when found

### Web UI

Open `https://TAILSCALE_IP:5679/` in browser:
- Live serial terminal
- Reset button
- Bootloader button
- Baud rate selector
- Status display

## Architecture

```
┌─────────────┐      Tailscale       ┌─────────────┐      USB      ┌─────────┐
│  Container  │  ←─────────────────►  │   Bridge    │  ←─────────►  │  ESP32  │
│   (D'ENT)   │    HTTPS/WSS         │   (MacBook) │               │   P4    │
└─────────────┘                       └─────────────┘               └─────────┘
```

## Integration

See [esp32-p4 skill](../esp32-p4/) for complete workflow.

## License

MIT - Studio Alight 2026
