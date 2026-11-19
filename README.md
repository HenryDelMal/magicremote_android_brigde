# Magic Remote pointer for Google TV

Use an LG Magic Remote as a pointer on a Chromecast with Google TV.

## How it works

The LG TV calculates the pointer position. The bridge runs on the LG TV by default and forwards motion through ADB to a temporary Android mouse. Use `--pc-bridge` to run it on a computer instead. The center button taps at the pointer, Home opens Google TV Home, and Input or 123 hands control back to webOS.

## Tested with

- LG QNED82ASG running webOS 25 with an MR25GA Magic Remote
- Chromecast with Google TV 4K running Android 14
- Bridge running directly on webOS and on macOS

The Android cursor tap uses the cursor overlay reported by the tested Android 14 build.

## Requirements

The LG TV needs root access and Python 3. The Chromecast needs wireless ADB debugging and an authorized ADB connection with access to Android's HID tool. Chromecast root is unnecessary.

See [INSTALL.md](INSTALL.md) for setup and use.

The optional LG Homebrew app manages pairing, connection settings, and Start/Stop on the TV.
