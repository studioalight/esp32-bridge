# ESP32 Bridge v2.0

Network bridge for ESP32 development - serial monitor + firmware flashing over WebSocket.

## Features

- **Serial Monitoring** - Live streaming over WebSocket with auto-reconnect
- **USB Hotplug Support** - Detects unplugging/replugging automatically
- **Smart Reconnection** - Tracks devices by hardware ID, waits 30s for same device
- **ESP32-Only Filtering** - Excludes debug consoles, Bluetooth, and non-ESP32 devices
- **Firmware Flashing** - via esptool with progress tracking
- **Batch Flash** - Atomic multi-file flashing in single esptool invocation
- **Chip ID Detection** - Auto-detects connected device type and MAC
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

// Flash single file (legacy)
{"action": "flash", "file": "firmware.bin", "addr": "0x10000", "rate": 1500000}

// Flash batch (atomic multi-file)
{
  "action": "flash_batch",
  "files": [
    {"filename": "bootloader.bin", "addr": "0x2000"},
    {"filename": "partition-table.bin", "addr": "0x8000"},
    {"filename": "app.bin", "addr": "0x10000"}
  ],
  "rate": 1500000,
  "reset_after": true
}

// Get status
{"action": "status"}

// Change baud rate
{"action": "set_baud", "rate": 921600}

// Get config
{"action": "get_config"}

// Get current chip type
{"action": "get_chip"}

// Set chip type
{"action": "set_chip", "chip": "esp32p4"}

// Get chip ID from connected device
{"action": "get_chip_id"}
// Response: {"type": "chip_id", "chip_id": "80:b5:4e:f3:2d:04", "mac": "80:b5:4e:f3:2d:04", "target": "esp32s3", "status": "connected"}
// Note: Device automatically resets back to app mode after detection
```

### Responses

**Batch flash progress:**
```json
{"type": "flash_batch", "status": "file_start", "file_num": 1, "total": 4}
{"type": "flash_batch", "status": "progress", "line": "Writing at 0x00002000... (5 %)"}
{"type": "flash_batch", "status": "file_complete", "file_num": 1}
{"type": "flash_batch", "status": "complete", "time": "45.2s", "reset_performed": true}
```

**Error:**
```json
{"type": "flash_batch", "status": "error", "message": "File not found: app.bin", "at_file": "app.bin"}
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

### Smart Device Reconnection

When a device disconnects:
1. Bridge remembers device HWID (USB VID:PID:Serial)
2. Waits 30s for same device to reconnect
3. Shows countdown: "Waiting for device USB VID:PID=303A:1001..."
4. After timeout, accepts any ESP32 device
5. Updates tracking for new device

### ESP32-Only Port Filtering

The bridge automatically excludes:
- Debug consoles (`/dev/cu.debug-console`)
- Bluetooth ports (`/dev/cu.Bluetooth-Incoming-Port`)
- Non-ESP32 USB devices

Only accepts ports with:
- ESP32 keywords in description (USB JTAG, CP210, CH340, etc.)
- Known ESP32 vendor IDs (303A=Espressif, 10C4=Silicon Labs, 1A86=QinHeng)

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

### ESP-IDF Project Builder Skill

See [esp-idf-project-builder skill](../esp-idf-project-builder/) for complete workflow:
- Device discovery and verification
- Config-free flashing (reads addresses from build artifacts)
- Target mismatch detection
- High-speed flashing (3Mbps)

### ESP32-P4 Skill (Legacy)

See [esp32-p4 skill](../esp32-p4/) for ESP32-P4 specific workflow.

## License

MIT - Studio Alight 2026
