# AOSP Build Script

Automated Custom Rom build script with Telegram notifications and GoFile upload.

## Requirements

```bash
pip3 install requests
```

- Python 3.8+
- `repo`, `git`, `jq`

## Usage

```bash
./build.py <device> [options]
```

`<device>` can be a codename (looks up `devices/<codename>.json`) or a direct path to a device JSON file.

### Options

- `--rom NAME_OR_PATH` ROM name from `roms/<name>.json` or path to a ROM JSON file (default: `pixelos`)
- `--skip-sync` Skip source sync
- `--skip-clone` Skip device repo cloning
- `--skip-upload` Skip GoFile upload
- `--clean-repos` Clean device repos before cloning
- `--build-dir PATH` Custom build directory (default: `~/<ROM name>`)

### Examples

```bash
# Full build using default ROM config: roms/pixelos.json
./build.py spartan

# Build with explicit ROM config name
./build.py spartan --rom pixelos

# Build with custom ROM config file
./build.py spartan --rom ./roms/myrom.json

# Incremental build (skip sync + clone)
./build.py spartan --skip-sync --skip-clone

# Build without upload
./build.py spartan --skip-upload
```

## Device Configuration

Add device configs to `devices/<codename>.json`:

```json
{
  "device": {
    "codename": "spartan",
    "full_name": "Realme GT Neo 3T"
  },
  "build": {
    "variant": "user",
    "target_release": "bp3a"
  },
  "environment": {
    "UNSAFE_DISABLE_HIDDENAPI_FLAGS": "true"
  },
  "repositories": {
    "device_tree": {
      "url": "https://github.com/...",
      "branch": "sixteen-qpr1",
      "path": "device/realme/spartan"
    }
  }
}
```

## ROM Configuration

ROM configs live in `roms/`. Use `roms/rom-template.json` as a starting point.

Example (`roms/pixelos.json`):

```json
{
  "name": "PixelOS",
  "manifest": {
    "url": "https://github.com/PixelOS-AOSP/android_manifest.git",
    "branch": "sixteen-qpr1"
  },
  "sync_jobs": 24,
  "build": {
    "envsetup": "build/envsetup.sh"
  },
  "output": {
    "pattern": "*PixelOS*.zip"
  }
}
```

## Telegram Notifications

Option 1: set environment variables

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"
```

Option 2: interactive prompt (script asks if vars are missing)

Disable notifications:

```bash
export TELEGRAM_DISABLE=true
```

## Features

- Real-time build progress
- Single Telegram message updated in place
- Automatic GoFile upload with SHA256
- JSON-based device and ROM configs
- Non-blocking Telegram notifications
- Prompt-driven init/cleanup/build commands per run
