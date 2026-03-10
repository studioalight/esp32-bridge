# Installation

## Method 1: Using pip

```bash
pip install -r requirements.txt
```

Or install specific versions:
```bash
pip install pyserial websockets aiohttp pyyaml

# Critical: ESP32-P4 requires esptool v4.4+
pip install esptool>=4.4
```

Verify esptool supports ESP32-P4:
```bash
esptool.py --chip esp32p4 version
# Should show: esptool.py v4.x or higher
```

---

## Method 2: Using uv (Recommended)

`uv` is a fast Python package manager from Astral.

### Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv
```

### Install dependencies with uv:
```bash
# Create virtual environment
uv venv

# Activate
source .venv/bin/activate

# Install requirements
uv pip install -r requirements.txt

# Or one-shot:
uv pip install pyserial websockets aiohttp pyyaml esptool>=4.4
```

### Verify installation:
```bash
uv run esptool.py --chip esp32p4 version
```

---

## Method 3: One-command install (uv)

```bash
# Install esptool with specific version for ESP32-P4
uv pip install esptool==4.8.1
```

Recommended esptool versions:
- **v4.8.1** - Latest stable with ESP32-P4 support
- **v4.7.0** - Minimum for ESP32-P4
- **v4.4.0** - First with ESP32-P4 support

---

## ESP32-P4 Support Check

Test that esptool recognizes ESP32-P4:

```bash
esptool.py --chip esp32p4 flash_id
```

If you get `error: argument --chip: invalid choice: 'esp32p4'`
→ Upgrade esptool: `pip install --upgrade esptool>=4.4`

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'esptool'"

Install in the same environment:
```bash
which python3
# Use that Python to install:
/path/to/python3 -m pip install esptool>=4.4
```

### Permission denied

Use `--user` flag:
```bash
pip install --user esptool>=4.4
```

Or use uv (recommended, installs to local venv).
