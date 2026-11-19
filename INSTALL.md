# Install and run

Run the bridge directly on the rooted LG webOS TV by default. Use `--pc-bridge` to run it on a computer instead. Android creates a temporary virtual mouse while the bridge is running.

## Requirements

- A rooted LG webOS TV with Python 3 and access to a root shell.
- For Mac-hosted mode, a Mac with Python 3 and [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools), including `adb`.
- A Chromecast with Google TV with wireless debugging enabled and an authorized ADB connection.
- The Chromecast's ADB shell user needs access to `/dev/uhid` and `/system/bin/hid`. Android root is not required. This access was verified on the tested Chromecast running Android 14.
- TV-hosted mode also needs an ADB executable compatible with the LG TV's CPU and userspace, with wireless pairing support. The TV's ADB identity must be paired with the Chromecast separately from any Mac identity.

On the LG, the bridge reads the computed pointer from `LGE M-RCU - Builtin [0]`. Its exact event path is detected at startup.

## Connect ADB

On the Chromecast, enable Developer options and Wireless debugging. In its Wireless debugging settings, use **Pair device with pairing code**. Run these commands on the system that will host the bridge. Replace the placeholder addresses and ports with the values on the Chromecast:

```sh
adb pair 'CHROMECAST_IP:PAIRING_PORT'
adb connect 'CHROMECAST_IP:ADB_PORT'
adb devices -l
```

The pairing port and ADB connection port can differ. Use the port shown for each operation. Accept the authorization prompt on the Chromecast if it appears. Use the serial printed by `adb devices -l` in the commands below.

## Check ADB mouse support

From this repository directory, send a short synthetic motion test:

```sh
python3 magic_remote_adb.py \
  --adb-serial 'ADB_SERIAL' \
  --probe
```

The pointer should move in a small square. This checks the Chromecast ADB mouse path without connecting to the LG.

## Start the bridge

### LG TV (default)

TV-hosted mode runs the pointer reader and ADB client on the LG. The Mac is used for initial file transfer and setup, then is not needed while the bridge is running.

Copy `magic_remote_adb.py` to the TV over root SSH. Place a compatible ADB executable on the TV and make it available on `PATH`, or note its full path for `--adb`. The ADB build must match the TV's userspace and support wireless pairing. The tested LG used [Debian ADB 34.0.5 for ARM hard-float](https://packages.debian.org/bookworm-backports/armhf/adb), with its loader and libraries kept in a separate directory. When running ADB through a private loader, start its server explicitly with `adb server nodaemon` in a separate shell before running the client commands.

On the Chromecast, enable **Wireless debugging** and open **Pair device with pairing code**. From an LG root shell, pair the TV's own ADB identity using the pairing address, port, and code shown on the Chromecast:

```sh
adb pair 'CHROMECAST_IP:PAIRING_PORT'
adb connect 'CHROMECAST_IP:ADB_PORT'
adb devices -l
```

Use the serial returned by `adb devices -l`. Pair the TV separately from the Mac. The TV must be able to reach the Chromecast on the network. If the wireless debugging connection port changes, reconnect with the new port and use the updated serial.

Start the local bridge on the TV:

```sh
python3 /path/to/magic_remote_adb.py \
  --adb '/path/to/adb' \
  --adb-serial 'ADB_SERIAL' \
  --exclusive \
  --tap-under-pointer \
  --lg-input com.webos.app.hdmi1
```

If the ADB executable is on `PATH`, omit `--adb`. Use the webOS app ID for the HDMI input connected to the Chromecast. Press Ctrl+C in the LG shell to stop the bridge.

### Computer bridge (optional)

The Mac must be on the same network as the LG TV and Chromecast. It runs the reader over SSH and uses its own paired ADB identity to control Android. No ADB executable is needed on the TV for this mode.

Enable root SSH access on the rooted TV and confirm that the Mac can connect as root. If SSH uses a nonstandard port or identity file, supply `--ssh-port` or `--ssh-identity`.

You can also use `--telnet-host <TV_IP>` if the TV already has a Telnet shell enabled on your local network. Telnet sends commands and input data without SSH encryption. Use SSH when available.

Replace the serial and TV host. Choose the webOS app ID for the LG HDMI input connected to the Chromecast:

```sh
python3 magic_remote_adb.py --pc-bridge \
  --adb-serial 'ADB_SERIAL' \
  --tv 'root@TV_IP' \
  --exclusive \
  --tap-under-pointer \
  --lg-input com.webos.app.hdmi1
```

For an SSH identity file and port:

```sh
python3 magic_remote_adb.py --pc-bridge \
  --adb-serial 'ADB_SERIAL' \
  --tv 'root@TV_IP' \
  --ssh-identity 'SSH_KEY_PATH' \
  --ssh-port 'SSH_PORT' \
  --exclusive \
  --tap-under-pointer \
  --lg-input com.webos.app.hdmi1
```

For an already enabled local Telnet service, replace the `--tv` option with:

```sh
--telnet-host 'TV_IP'
```

Keep the Mac connected to the TV and Chromecast while using the bridge. Press Ctrl+C in the terminal to stop it.

## LG Homebrew app

**Magic Remote Bridge** gives you a TV screen for pairing, connection settings, status, and starting or stopping the TV-hosted bridge. The root-enabled Homebrew Channel must be installed.

1. Set up the TV-hosted runtime as described above. The app expects `magic_remote_adb.py` and an executable ADB launcher named `tv-adb` in `/media/developer/magicremote-android-bridge/`.
2. Copy `webos/control.py` into the same directory as `control.py`.
3. Build the app with the [webOS CLI](https://webostv.developer.lge.com/develop/tools/cli-dev-guide) using `ares-package webos/app`. Install the resulting IPK on the TV with Homebrew or `ares-install`.
4. Open **Magic Remote Bridge** from the LG home screen. Save the Chromecast's wireless debugging address and connection port, select the HDMI input, and press **Start bridge**. If the TV hasn't paired with the Chromecast yet, use **Pair Chromecast** with the separate pairing port and one-time code displayed by Android.
5. Return to the selected HDMI input to use the remote with the Chromecast.

## Use the remote

- Move the Magic Remote to move the Android pointer.
- Press center to tap the item at the pointer.
- Use the direction buttons and Back for Android navigation.
- Press Home to open Google TV Home.
- Volume and Mute still control the LG TV. Channel Up and Down go to Google TV on the Chromecast HDMI input and work in apps that handle channel keys.
- Press the LG Input or 123 button to return remote control to webOS. The bridge hands control back when the selected HDMI app is in the foreground. If the input chooser remains in front, dismiss it with Back. The bridge resumes control on the selected HDMI app.

The bridge holds exclusive access to the LG remote input while the Chromecast HDMI app is active. If the bridge exits or stops renewing its input lease, the TV releases the remote.

## Limitations

Pointer tapping reads the Android cursor overlay position from the tested Chromecast's Android 14 SurfaceFlinger output. Other Android builds may report this overlay differently. If the pointer moves but taps do not land under it, the overlay format may differ.

The LG cursor can still appear over HDMI. Pointer coordinates stop changing when the LG pointer reaches an edge of the LG screen. Move it back toward the center to continue moving the Android cursor.

The tap setup was tested with Chromecast HDMI-CEC disabled. If a button triggers two actions, check whether CEC is also forwarding it.
