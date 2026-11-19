# Install and run

The bridge runs on a Mac on the same network as the LG TV and Chromecast. It does not install software on either device. Android creates a temporary virtual mouse while the bridge is running.

## Requirements

- A rooted LG webOS TV with Python 3 and root SSH access enabled.
- A Mac with Python 3 and [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools), including `adb`.
- A Chromecast with Google TV with wireless debugging enabled and an authorized ADB connection.
- The Chromecast's ADB shell user needs access to `/dev/uhid` and `/system/bin/hid`. Android root is not required. This access was verified on the tested Chromecast running Android 14.

The TV and Chromecast must be reachable from the Mac. On the LG, the bridge reads the computed pointer from `LGE M-RCU - Builtin [0]`. Its exact event path is detected at startup.

## Connect ADB

On the Chromecast, enable Developer options and Wireless debugging. In its Wireless debugging settings, use **Pair device with pairing code**. Replace the placeholder addresses and ports with the values on the Chromecast:

```sh
adb pair 'CHROMECAST_IP:PAIRING_PORT'
adb connect 'CHROMECAST_IP:ADB_PORT'
adb devices -l
```

The pairing port and ADB connection port can differ. Use the port shown for each operation. Accept the authorization prompt on the Chromecast if it appears. Use the serial printed by `adb devices -l` in the commands below.

## Connect to the LG TV

Enable root SSH access on the rooted TV and confirm that the Mac can connect as root. If SSH uses a nonstandard port or identity file, supply `--ssh-port` or `--ssh-identity`.

You can also use `--telnet-host <TV_IP>` if the TV already has a Telnet shell enabled on your local network. Telnet sends commands and input data without SSH encryption. Use SSH when available.

## Check ADB mouse support

From this repository directory, send a short synthetic motion test:

```sh
python3 magic_remote_adb.py \
  --adb-serial 'ADB_SERIAL' \
  --probe
```

The pointer should move in a small square. This checks the Chromecast ADB mouse path without connecting to the LG.

## Start the bridge

Replace the serial and TV host. Choose the webOS app ID for the LG HDMI input connected to the Chromecast:

```sh
python3 magic_remote_adb.py \
  --adb-serial 'ADB_SERIAL' \
  --tv 'root@TV_IP' \
  --exclusive \
  --tap-under-pointer \
  --lg-input com.webos.app.hdmi1
```

For an SSH identity file and port:

```sh
python3 magic_remote_adb.py \
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

## Use the remote

- Move the Magic Remote to move the Android pointer.
- Press center to tap the item at the pointer.
- Use the direction buttons and Back for Android navigation.
- Press Home to open Google TV Home.
- Press the LG Input or 123 button to return remote control to webOS. The bridge hands control back when the selected HDMI app is in the foreground. If the input chooser remains in front, dismiss it with Back. The bridge resumes control on the selected HDMI app.

The bridge holds exclusive access to the LG remote input while the Chromecast HDMI app is active. If the Mac loses its connection, the TV's input lease expires and releases the remote.

## Limitations

Pointer tapping reads the Android cursor overlay position from the tested Chromecast's Android 14 SurfaceFlinger output. Other Android builds may report this overlay differently. If the pointer moves but taps do not land under it, the overlay format may differ.

The LG cursor can still appear over HDMI. Pointer coordinates stop changing when the LG pointer reaches an edge of the LG screen. Move it back toward the center to continue moving the Android cursor.

The tap setup was tested with Chromecast HDMI-CEC disabled. If a button triggers two actions, check whether CEC is also forwarding it.
