#!/usr/bin/env python3
"""Homebrew app controller for the Magic Remote Android bridge."""

import base64
import fcntl
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


CONTROL_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = (CONTROL_DIR if (CONTROL_DIR / "magic_remote_adb.py").exists()
               else CONTROL_DIR.parent)
CONFIG_PATH = Path("/var/lib/webosbrew/magicremote-bridge.json")
LOCK_PATH = Path("/var/lib/webosbrew/magicremote-bridge.lock")
APP_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,127}$")
DEFAULT_HDMI_APP = "com.webos.app.hdmi1"
ADB = RUNTIME_DIR / "tv-adb"
BRIDGE = RUNTIME_DIR / "magic_remote_adb.py"
PID_FILE = RUNTIME_DIR / "bridge.pid"
LOG_FILE = RUNTIME_DIR / "bridge.log"


class ControlError(Exception):
    pass


def emit(result):
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


def run(command, *, timeout=8, input_text=None):
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(RUNTIME_DIR),
        )
    except subprocess.TimeoutExpired as error:
        raise ControlError("The device command timed out.") from error
    except OSError as error:
        raise ControlError("Could not run the configured ADB executable.") from error


def validate_host(value):
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise ControlError("Enter a valid Chromecast IP address.")
    if address.version != 4:
        raise ControlError("The Chromecast address must be IPv4.")
    return str(address)


def validate_port(value, label="connection"):
    if isinstance(value, bool):
        raise ControlError(f"Enter a valid {label} port.")
    try:
        port = int(value)
    except (ValueError, TypeError):
        raise ControlError(f"Enter a valid {label} port.")
    if not 1 <= port <= 65535:
        raise ControlError(f"Enter a valid {label} port.")
    return port


def validate_app_id(value):
    if not isinstance(value, str) or not APP_ID_PATTERN.fullmatch(value):
        raise ControlError("Enter a valid webOS HDMI app ID.")
    if not value.startswith("com.webos.app.hdmi"):
        raise ControlError("The app ID must identify an LG HDMI input.")
    return value


def load_config():
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            raw = json.load(config_file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ControlError("Saved Chromecast settings could not be read.")
    if not isinstance(raw, dict):
        raise ControlError("Saved Chromecast settings are invalid.")
    return {
        "host": validate_host(raw.get("host")),
        "port": validate_port(raw.get("port")),
        "hdmiApp": validate_app_id(raw.get("hdmiApp", DEFAULT_HDMI_APP)),
    }


def save_config(data):
    if not isinstance(data, dict):
        raise ControlError("Chromecast settings are missing.")
    config = {
        "host": validate_host(data.get("host")),
        "port": validate_port(data.get("port")),
        "hdmiApp": validate_app_id(data.get("hdmiApp", DEFAULT_HDMI_APP)),
    }
    CONFIG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".magicremote-", dir=str(CONFIG_PATH.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as config_file:
            json.dump(config, config_file, separators=(",", ":"))
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        os.replace(temporary_path, CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return config


def bridge_pid():
    try:
        value = PID_FILE.read_text(encoding="ascii").strip()
        pid = int(value)
        if pid <= 1:
            return None
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        command_line = [part.decode("utf-8", "replace") for part in command_line if part]
    except (OSError, ValueError):
        return None

    script_index = next((i for i, part in enumerate(command_line)
                         if Path(part).name == BRIDGE.name), None)
    if script_index is None:
        return None
    script = Path(command_line[script_index])
    if not script.is_absolute():
        try:
            script = Path(os.readlink(f"/proc/{pid}/cwd")) / script
        except OSError:
            return None
    if script.resolve() != BRIDGE:
        return None
    required_flags = {"--local-tv", "--exclusive", "--tap-under-pointer"}
    if not required_flags.issubset(command_line[script_index + 1:]):
        return None
    return pid


def adb_server_ready():
    try:
        with socket.create_connection(("127.0.0.1", 5037), timeout=0.5) as connection:
            connection.settimeout(0.5)
            connection.sendall(b"000chost:version")
            return connection.recv(4) == b"OKAY"
    except OSError:
        return False


def ensure_adb_server():
    if adb_server_ready():
        return
    try:
        server_log = open(RUNTIME_DIR / "adb-server.log", "ab", buffering=0)
        subprocess.Popen(
            [str(ADB), "server", "nodaemon"],
            stdin=subprocess.DEVNULL,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            cwd=str(RUNTIME_DIR),
            start_new_session=True,
            close_fds=True,
        )
    except OSError as error:
        raise ControlError("Could not start the TV's ADB server.") from error
    for _ in range(30):
        if adb_server_ready():
            return
        time.sleep(0.2)
    raise ControlError("The TV's ADB server did not start.")


def adb_devices():
    ensure_adb_server()
    result = run([str(ADB), "devices", "-l"])
    if result.returncode:
        raise ControlError("Could not list ADB devices.")
    return result.stdout


def connect_chromecast(config):
    ensure_adb_server()
    endpoint = f"{config['host']}:{config['port']}"
    result = run([str(ADB), "connect", endpoint], timeout=8)
    if result.returncode or "connected to" not in result.stdout.lower():
        # ADB can report "already connected" with success as well.
        if "already connected" not in result.stdout.lower():
            raise ControlError("Could not connect to the Chromecast. Check its address and port.")
    devices = run([str(ADB), "devices", "-l"], timeout=5)
    for line in devices.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == endpoint and fields[1] == "device":
            return endpoint
    raise ControlError("The Chromecast is not authorized for this TV's ADB connection.")


def status(config=None):
    if config is None:
        try:
            config = load_config()
        except ControlError:
            config = None
    pid = bridge_pid()
    connected = False
    if config:
        endpoint = f"{config['host']}:{config['port']}"
        try:
            for line in adb_devices().splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[0] == endpoint and fields[1] == "device":
                    connected = True
                    break
        except ControlError:
            pass
    return {
        "running": pid is not None,
        "adbConnected": connected,
        "configured": config is not None,
        "serial": f"{config['host']}:{config['port']}" if config else "",
        "hdmiApp": config["hdmiApp"] if config else DEFAULT_HDMI_APP,
    }


def action_configure(data):
    config = save_config(data)
    return status(config)


def action_pair(data):
    if not isinstance(data, dict):
        raise ControlError("Pairing details are missing.")
    host = validate_host(data.get("host"))
    port = validate_port(data.get("pairingPort"), "pairing")
    code = data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ControlError("Enter the six-digit pairing code shown on the Chromecast.")
    ensure_adb_server()
    result = run([str(ADB), "pair", f"{host}:{port}"], timeout=35,
                 input_text=code + "\n")
    if result.returncode or "successfully paired" not in result.stdout.lower():
        raise ControlError("Pairing failed. Check the code and pairing port, then try again.")
    return {"paired": True, "message": "Paired. Save the Chromecast connection port to continue."}


def action_start(config):
    if not config:
        raise ControlError("Enter and save the Chromecast address and HDMI input first.")
    if bridge_pid() is not None:
        return status(config)
    serial = connect_chromecast(config)
    with open(LOG_FILE, "ab", buffering=0) as bridge_log:
        try:
            process = subprocess.Popen(
                [sys.executable or "/usr/bin/python3", "-u", str(BRIDGE), "--local-tv",
                 "--adb", str(ADB), "--adb-serial", serial,
                 "--exclusive", "--tap-under-pointer", "--lg-input", config["hdmiApp"]],
                stdin=subprocess.DEVNULL,
                stdout=bridge_log,
                stderr=subprocess.STDOUT,
                cwd=str(RUNTIME_DIR),
                start_new_session=True,
                close_fds=True,
            )
        except OSError as error:
            raise ControlError("Could not start the pointer bridge.") from error
    PID_FILE.write_text(f"{process.pid}\n", encoding="ascii")
    os.chmod(PID_FILE, 0o600)
    for _ in range(30):
        if bridge_pid() is not None:
            return status(config)
        if process.poll() is not None:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
            raise ControlError("The pointer bridge stopped during startup. Check the TV bridge log.")
        time.sleep(0.1)
    return status(config)


def action_stop():
    pid = bridge_pid()
    if pid is None:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return status()
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise ControlError("Could not stop the pointer bridge.") from error
    for _ in range(30):
        if bridge_pid() is None:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
            return status()
        time.sleep(0.1)
    raise ControlError("The pointer bridge is still stopping. Try again shortly.")


def perform(action, data):
    if action == "status":
        return status()
    with open(LOCK_PATH, "a+") as lock:
        os.chmod(LOCK_PATH, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if action == "configure":
            return action_configure(data)
        if action == "pair":
            return action_pair(data)
        if action == "start":
            return action_start(load_config())
        if action == "stop":
            return action_stop()
    raise ControlError("Unknown bridge action.")


def main(argv):
    try:
        if not argv or len(argv) > 2:
            raise ControlError("Invalid app request.")
        action = argv[0]
        if action not in {"status", "start", "stop", "configure", "pair"}:
            raise ControlError("Unknown bridge action.")
        data = {}
        if len(argv) == 2:
            if len(argv[1]) > 8192:
                raise ControlError("App request is too large.")
            data = json.loads(base64.b64decode(argv[1], validate=True).decode("utf-8"))
        emit(perform(action, data))
    except ControlError as error:
        emit({"error": str(error)})
    except (ValueError, UnicodeDecodeError):
        emit({"error": "App request data is invalid."})
    except Exception:
        emit({"error": "The bridge controller encountered an unexpected error."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
