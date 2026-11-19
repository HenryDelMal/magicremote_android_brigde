#!/usr/bin/env python3
"""Forward an LG Magic Remote pointer to a Chromecast through ADB UHID."""

import argparse
import base64
import json
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path


IME_HELPER_DEVICE_PATH = "/data/local/tmp/magicremote-ime-click.dex"

# Four-byte HID mouse report: buttons, relative X/Y, and vertical wheel.
HID_MOUSE_REPORT_MAP = [
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x02,  # Usage (Mouse)
    0xA1, 0x01,  # Collection (Application)
    0x09, 0x01,  #   Usage (Pointer)
    0xA1, 0x00,  #   Collection (Physical)
    0x05, 0x09,  #     Usage Page (Buttons)
    0x19, 0x01,  #     Usage Minimum (1)
    0x29, 0x03,  #     Usage Maximum (3)
    0x15, 0x00,  #     Logical Minimum (0)
    0x25, 0x01,  #     Logical Maximum (1)
    0x95, 0x03,  #     Report Count (3)
    0x75, 0x01,  #     Report Size (1)
    0x81, 0x02,  #     Input (Data, Variable, Absolute)
    0x95, 0x01,  #     Report Count (1)
    0x75, 0x05,  #     Report Size (5)
    0x81, 0x03,  #     Input (Constant, 5-bit padding)
    0x05, 0x01,  #     Usage Page (Generic Desktop)
    0x09, 0x30,  #     Usage (X)
    0x09, 0x31,  #     Usage (Y)
    0x09, 0x38,  #     Usage (Wheel)
    0x15, 0x81,  #     Logical Minimum (-127)
    0x25, 0x7F,  #     Logical Maximum (127)
    0x75, 0x08,  #     Report Size (8)
    0x95, 0x03,  #     Report Count (3)
    0x81, 0x06,  #     Input (Data, Variable, Relative)
    0xC0,        #   End Collection
    0xC0,        # End Collection
]


REMOTE_READER = r'''import fcntl,json,os,re,select,struct,subprocess,sys,threading,time
grab_seconds=GRAB_SECONDS
native_keys=NATIVE_KEYS
tap_mode=TAP_MODE
exclusive=EXCLUSIVE
lg_input=LG_INPUT
# Linux evdev key codes mapped to Android key codes. This LG emits KEY_PREVIOUS
# (412) for the Magic Remote's Back button.
android_keys={28:23,103:19,105:21,106:22,108:20,158:4,174:4,272:23,352:23,412:4,773:3}
channel_keys={402:166,403:167}
volume_keys=(113,114,115)
# LG's dedicated Input Source and 123/Screen Remote keys, respectively.
handoff_keys=(241,994)
grab_request=0x40044590
name="LGE M-RCU - Builtin [0]"
try:
 text=open("/proc/bus/input/devices",encoding="utf-8",errors="replace").read()
 block=next(b for b in text.split("\n\n") if name in b)
 event=re.search(r"Handlers=.*\b(event\d+)\b",block).group(1)
 path="/dev/input/"+event
 access=os.O_RDWR if lg_input else os.O_RDONLY
 fd=os.open(path,access|os.O_NONBLOCK)
 grabbed=bool(grab_seconds or (exclusive and not lg_input))
 if grabbed: fcntl.ioctl(fd,grab_request,1)
except Exception as e:
 print(json.dumps({"error":"Cannot open Magic Remote input device: %s"%e}),flush=True);sys.exit(2)
fmt="<IIHHi" if struct.calcsize("P")==4 else "<QQHHi"
size=struct.calcsize(fmt)
foreground=None
def watch_foreground():
 global foreground
 while True:
  try:
   reply=subprocess.check_output(["luna-send","-n","1",
    "luna://com.webos.applicationManager/getForegroundAppInfo",
    '{"extraInfo":true}'],timeout=2)
   apps=json.loads(reply)["foregroundAppInfo"]
   foreground=tuple(app["appId"] for app in apps if app.get("displayId",0)==0)
  except (OSError,ValueError,KeyError,subprocess.SubprocessError):
   foreground=None
  time.sleep(.35)
if lg_input: threading.Thread(target=watch_foreground,daemon=True).start()
def abspos(axis):
 request=(2<<30)|(24<<16)|(ord("E")<<8)|(0x40+axis)
 return struct.unpack("<6i",fcntl.ioctl(fd,request,bytes(24)))[:3]
try:
 x,xmin,xmax=abspos(0); y,ymin,ymax=abspos(1)
except Exception:
 x=y=None
deadline=time.monotonic()+grab_seconds if grab_seconds else None
lease=time.monotonic()+10
inputs=[fd,0] if exclusive else [fd]
print(json.dumps({"ready":path,"x":x,"y":y}),flush=True)
px,py=x,y; nx,ny=x,y; has=False; buttons=0; changed=False; wheel=0
handed_off=False; saw_dialog=False; resume_at=0; ignore_dismiss_until=0
try:
 while deadline is None or time.monotonic()<deadline:
  if exclusive and time.monotonic()>lease: break
  if lg_input:
   input_only=foreground==(lg_input,)
   if handed_off and not input_only and foreground is not None: saw_dialog=True
   if handed_off and input_only and (saw_dialog or resume_at) and time.monotonic()>=resume_at:
    handed_off=False; saw_dialog=False; resume_at=0
   want_grab=input_only and not handed_off
   if want_grab!=grabbed:
    fcntl.ioctl(fd,grab_request,int(want_grab)); grabbed=want_grab
    px=py=nx=ny=None; has=False; wheel=0
    if buttons: print(json.dumps({"report":[0,0,0,0]}),flush=True)
    buttons=0;changed=False
    print(json.dumps({"lg_control":not grabbed}),flush=True)
  readable,_,_=select.select(inputs,[],[],.2 if lg_input else 1)
  if 0 in readable:
   if not os.read(0,1024): break
   lease=time.monotonic()+10
  if fd not in readable: continue
  data=os.read(fd,size*64)
  if not data: raise RuntimeError("Magic Remote input device closed")
  for offset in range(0,len(data)-size+1,size):
   _,_,typ,code,val=struct.unpack_from(fmt,data,offset)
   if lg_input and not grabbed:
    if (handed_off and typ==1 and val==0 and code in (158,174,412)+handoff_keys
        and time.monotonic()>=ignore_dismiss_until):
     resume_at=time.monotonic()+.7
    continue
   if lg_input and typ==1 and code in handoff_keys:
    if val==0:
     fcntl.ioctl(fd,grab_request,0); grabbed=False
     handed_off=True; saw_dialog=False; resume_at=0
     ignore_dismiss_until=time.monotonic()+.6
     px=py=nx=ny=None; has=False; wheel=0
     if buttons: print(json.dumps({"report":[0,0,0,0]}),flush=True)
     buttons=0;changed=False
     print(json.dumps({"lg_control":True}),flush=True)
     for value in (1,0):
      os.write(fd,struct.pack(fmt,0,0,1,code,value)+struct.pack(fmt,0,0,0,0,0))
    continue
   if typ==1 and (exclusive or grab_seconds) and code in volume_keys:
    if val==1 or (val==2 and code!=113):
     try:
      subprocess.run(["luna-send","-n","1",
       "luna://com.webos.service.networkinput/test/sendKeyCode",
       json.dumps({"keyCode":code})],stdout=subprocess.DEVNULL,
       stderr=subprocess.DEVNULL,timeout=1)
     except (OSError,subprocess.SubprocessError):
      pass
   elif typ==1 and (exclusive or grab_seconds) and code in channel_keys:
    if val in (1,2): print(json.dumps({"android_key":channel_keys[code]}),flush=True)
   elif typ==3 and code in (0,1):
    if code==0: nx=val
    else: ny=val
    has=True
   elif typ==2 and code==8: wheel+=val
   elif typ==1 and (native_keys or tap_mode) and code in android_keys and not (tap_mode and android_keys[code]==23):
    if val==1: print(json.dumps({"android_key":android_keys[code]}),flush=True)
   elif typ==1 and (code in (272,352) or ((grab_seconds or exclusive) and code==28)):
    old=buttons
    if val==1: buttons|=1
    elif val==0: buttons&=~1
    if old!=buttons: changed=True
   elif typ==0 and code==0:
    dx=dy=0
    if has:
     if None not in (px,py,nx,ny):
      rawx,rawy=nx-px,ny-py
      if abs(rawx)<400 and abs(rawy)<400: dx,dy=rawx,rawy
     px,py=nx,ny;has=False
    if dx or dy or wheel or changed:
     # Split large coordinate jumps into valid signed 8-bit HID reports.
     while dx or dy or wheel:
      sx=max(-127,min(127,dx)); sy=max(-127,min(127,dy)); sw=max(-127,min(127,wheel))
      print(json.dumps({"report":[buttons,sx&255,sy&255,sw&255]}),flush=True)
      dx-=sx;dy-=sy;wheel-=sw
     if changed: print(json.dumps({"report":[buttons,0,0,0]}),flush=True)
    wheel=0;changed=False
 if deadline is not None:
  print(json.dumps({"grab_finished":True}),flush=True)
finally: os.close(fd)
'''


def adb_command(serial, adb_path="adb"):
    return [adb_path, "-s", serial, "shell", "-T", "hid", "-"]


def write_hid(hid, message):
    hid.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    hid.stdin.flush()


def messages(remote):
    for line in remote.stdout:
        # Telnet also writes its banner, the shell prompt, and the echoed command.
        line = line.strip()
        if line.startswith('{"'):
            yield json.loads(line)


def open_reader(args):
    source = REMOTE_READER.replace("GRAB_SECONDS", str(args.grab_seconds), 1)
    source = source.replace("NATIVE_KEYS", repr(args.native_keys), 1)
    source = source.replace("TAP_MODE", repr(args.tap_under_pointer), 1)
    source = source.replace("EXCLUSIVE", repr(args.exclusive), 1)
    source = source.replace("LG_INPUT", repr(args.lg_input), 1)
    if args.local_tv:
        python = sys.executable or shutil.which("python3")
        if not python:
            raise RuntimeError("Cannot locate the TV's Python 3 executable")
        return subprocess.Popen(
            [python, "-u", "-c", source],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    payload = base64.b64encode(zlib.compress(source.encode())).decode()
    code = "import base64,zlib,sys;exec(zlib.decompress(base64.b64decode(sys.argv[1])))"
    script = None
    if args.telnet_host:
        command = ["telnet", args.telnet_host, "23"]
        chunks = (payload[index:index + 384] for index in range(0, len(payload), 384))
        # BusyBox limits the length of each interactive command line.
        script = "stty -echo; payload=\n"
        script += "".join(f"payload=\"${{payload}}{chunk}\"\n" for chunk in chunks)
        script += f"printf '\\n'; exec python3 -c {shlex.quote(code)} \"$payload\"\n"
    else:
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if args.ssh_identity:
            command += ["-i", args.ssh_identity, "-o", "IdentitiesOnly=yes"]
        if args.ssh_port:
            command += ["-p", str(args.ssh_port)]
        command += ["--", args.tv, "exec", "python3", "-c", shlex.quote(code), payload]
    remote = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, bufsize=1)
    try:
        if script is not None:
            time.sleep(0.35)
            remote.stdin.write(script)
            remote.stdin.flush()
        if not args.exclusive and not args.telnet_host:
            remote.stdin.close()
    except BaseException:
        remote.terminate()
        remote.wait()
        raise
    return remote


def renew_input_lease(remote, stop):
    while not stop.wait(2):
        try:
            remote.stdin.write("\n")
            remote.stdin.flush()
        except (OSError, ValueError):
            return


def prepare_ime_helper(serial, adb_path):
    helper = Path(__file__).with_name("ime-click.dex")
    if not helper.is_file():
        return False
    try:
        subprocess.run(
            [adb_path, "-s", serial, "push", str(helper), IME_HELPER_DEVICE_PATH],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        print("Could not load Android keyboard helper. Use D-pad selection.", file=sys.stderr)
        return False
    return True


class PersistentShell:
    """Keeps one ADB shell open for fast SurfaceFlinger cursor queries."""

    def __init__(self, serial, adb_path="adb"):
        self.serial = serial
        self.adb_path = adb_path
        self.proc = None

    def _ensure(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            [self.adb_path, "-s", self.serial, "shell", "-T"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )

    def run_lines(self, command):
        self._ensure()
        marker = "__END_SHELL_CMD__"
        self.proc.stdin.write(f"{command}\necho {marker}\n")
        self.proc.stdin.flush()
        lines = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self.close()
                raise RuntimeError("Persistent ADB shell closed")
            stripped = line.rstrip("\r\n")
            if stripped == marker:
                return lines
            lines.append(stripped)

    def close(self):
        if self.proc is not None:
            try:
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
            self.proc = None


class ImeDaemon:
    """Keeps ImeClick --daemon alive so keyboard clicks avoid ART/UiAutomation cold-starts."""

    def __init__(self, serial, adb_path="adb"):
        self.serial = serial
        self.adb_path = adb_path
        self.proc = None

    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return True
        try:
            self.proc = subprocess.Popen(
                [self.adb_path, "-s", self.serial, "shell", "-T",
                 f"CLASSPATH={IME_HELPER_DEVICE_PATH} app_process / ImeClick --daemon"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            ready = self.proc.stdout.readline().strip()
            if ready == "ready":
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        self.close()
        return False

    def click(self, x, y, pointer_selection=True):
        if not self.start():
            return None
        try:
            self.proc.stdin.write(f"{x} {y} {1 if pointer_selection else 0}\n")
            self.proc.stdin.flush()
            res = self.proc.stdout.readline().strip()
            if res in ("focused", "miss", "dpad", "no_ime"):
                return res
        except (OSError, subprocess.SubprocessError):
            pass
        self.close()
        return None

    def close(self):
        if self.proc is not None:
            try:
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.write("quit\n")
                    self.proc.stdin.flush()
                self.proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    self.proc.terminate()
                except OSError:
                    pass
            self.proc = None


def query_pointer_position(serial, adb_path="adb", shell_session=None):
    cmd = "dumpsys SurfaceFlinger | grep -B1 -A2 'parent=Sprite#' || true"
    if shell_session is not None:
        try:
            dump = "\n".join(shell_session.run_lines(cmd))
        except (OSError, RuntimeError, subprocess.SubprocessError):
            dump = subprocess.check_output(
                [adb_path, "-s", serial, "shell", "dumpsys", "SurfaceFlinger"],
                text=True, timeout=4,
            )
    else:
        dump = subprocess.check_output(
            [adb_path, "-s", serial, "shell", "dumpsys", "SurfaceFlinger"],
            text=True, timeout=4,
        )
    positions = re.findall(
        r"layerStack=\s*0[^\n]*?pos=\((-?[0-9.]+),\s*(-?[0-9.]+)\)[^\n]*\n"
        r"\s+parent=Sprite#\d+\n[^\n]*\n[^\n]*activeBuffer=\[\s*[1-9]",
        dump,
    )
    if len(positions) != 1:
        return None
    # The dump reports the top-left of the cursor sprite. Aim at its hotspot.
    return tuple(max(0, round(float(value)) + 7) for value in positions[0])


def tap_pointer(serial, adb_path="adb", ime_helper=False, pointer_selection=True,
                shell_session=None, ime_daemon=None):
    if ime_helper and ime_daemon is not None:
        if not pointer_selection:
            res = ime_daemon.click(-1, -1, pointer_selection=False)
            if res == "dpad":
                return
        pos = query_pointer_position(serial, adb_path, shell_session)
        if pos is None:
            print("Could not identify a single Android pointer position.", file=sys.stderr)
            return
        res = ime_daemon.click(pos[0], pos[1], pointer_selection=True)
        if res is not None:
            return

    shell = [adb_path, "-s", serial, "shell"]
    ime = subprocess.check_output(
        shell + ["dumpsys input_method | grep 'mInputShown=' || true"], text=True, timeout=4,
    )
    keyboard_visible = bool(re.search(r"\bmInputShown=true\b", ime))
    if keyboard_visible and (not ime_helper or not pointer_selection):
        subprocess.run(shell + ["input", "keyevent", "KEYCODE_DPAD_CENTER"], check=True, timeout=4)
        return
    pos = query_pointer_position(serial, adb_path, shell_session)
    if pos is None:
        print("Could not identify a single Android pointer position.", file=sys.stderr)
        return
    x, y = pos
    if keyboard_visible:
        # TV Gboard accepts center after input focus moves to the pointed key.
        try:
            result = subprocess.check_output(
                shell + [f"CLASSPATH={IME_HELPER_DEVICE_PATH}", "app_process", "/", "ImeClick",
                         str(x), str(y)], text=True, timeout=5,
            ).strip().splitlines()
            if result and result[-1] == "focused":
                subprocess.run(shell + ["input", "keyevent", "KEYCODE_DPAD_CENTER"], check=True, timeout=4)
            elif not result or result[-1] != "miss":
                print("Android keyboard click unavailable. Use D-pad selection.", file=sys.stderr)
        except (OSError, subprocess.SubprocessError):
            print("Android keyboard click failed. Use D-pad selection.", file=sys.stderr)
        return
    subprocess.run(shell + ["input", "touchscreen", "tap", str(x), str(y)], check=True, timeout=4)


def run_probe(serial, descriptor, adb_path="adb"):
    hid = subprocess.Popen(adb_command(serial, adb_path), stdin=subprocess.PIPE, text=True)
    try:
        write_hid(hid, {"id": 1, "command": "register", "name": "Magic Remote Bridge",
                        "vid": 51966, "pid": 1, "bus": "usb", "descriptor": descriptor})
        time.sleep(1)
        for dx, dy in ((30, 0), (0, 30), (-30, 0), (0, -30)):
            write_hid(hid, {"id": 1, "command": "report", "report": [0, dx & 0xFF, dy & 0xFF, 0]})
            time.sleep(0.12)
    finally:
        if hid.stdin:
            hid.stdin.close()
        status = hid.wait(timeout=5)
    if status:
        raise RuntimeError(f"Android HID probe exited with status {status}")
    print("Probe reports sent. The pointer should move in a small square.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb-serial", required=True, help="Chromecast serial from adb devices")
    parser.add_argument("--adb", default="adb", metavar="PATH",
                        help="ADB executable available on the current host (default: adb)")
    parser.add_argument("--pc-bridge", action="store_true",
                        help="Run on a computer and read the TV over SSH or Telnet (default: run on the LG TV)")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--tv", help="LG TV SSH destination for PC bridge mode")
    transport.add_argument("--local-tv", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ssh-identity", help="SSH private key path")
    parser.add_argument("--ssh-port", type=int, help="SSH port")
    transport.add_argument("--telnet-host", help="Use the TV's existing Telnet shell on port 23")
    parser.add_argument("--grab-seconds", type=int, default=0, choices=range(0, 61),
                        metavar="0–60", help="Temporarily give the bridge exclusive access to the TV input node")
    parser.add_argument("--native-keys", action="store_true",
                        help="During exclusive capture, send Android Select, Back, and direction keys")
    parser.add_argument("--exclusive", action="store_true",
                        help="Keep exclusive capture active while the host is connected")
    parser.add_argument("--tap-under-pointer", action="store_true",
                        help="Send an Android touchscreen tap at the pointer on a center press")
    parser.add_argument("--lg-input", metavar="APP_ID",
                        help="Capture only this LG HDMI input and hand Input or 123 to webOS")
    parser.add_argument("--probe", action="store_true", help="Send synthetic mouse motion without connecting to the TV")
    args = parser.parse_args()
    if args.pc_bridge and not (args.tv or args.telnet_host):
        parser.error("--pc-bridge requires --tv or --telnet-host")
    args.local_tv = not (args.tv or args.telnet_host)
    if args.exclusive and args.grab_seconds:
        parser.error("--exclusive replaces --grab-seconds")
    if (args.native_keys or args.tap_under_pointer) and not (args.grab_seconds or args.exclusive):
        parser.error("Button forwarding modes require exclusive capture")
    if args.native_keys and args.tap_under_pointer:
        parser.error("Choose either --native-keys or --tap-under-pointer")
    if args.lg_input and not args.exclusive:
        parser.error("--lg-input requires --exclusive")
    descriptor = HID_MOUSE_REPORT_MAP

    if args.probe:
        run_probe(args.adb_serial, descriptor, args.adb)
        return 0

    ime_helper = args.tap_under_pointer and prepare_ime_helper(args.adb_serial, args.adb)
    shell_session = PersistentShell(args.adb_serial, args.adb) if args.tap_under_pointer else None
    ime_daemon = ImeDaemon(args.adb_serial, args.adb) if ime_helper else None
    if ime_daemon is not None:
        ime_daemon.start()
    remote = open_reader(args)
    stop_lease = threading.Event()
    if args.exclusive:
        threading.Thread(target=renew_input_lease, args=(remote, stop_lease), daemon=True).start()
    adb = None
    pressed = False
    pointer_selection = True
    try:
        stream = messages(remote)
        status = next(stream, None)
        if status is None:
            code = remote.wait()
            raise RuntimeError(f"TV input reader exited during startup (status {code})")
        if "error" in status:
            raise RuntimeError(status["error"])
        print(f"Reading {status['ready']} on TV. Registering Chromecast mouse.", flush=True)
        adb = subprocess.Popen(adb_command(args.adb_serial, args.adb), stdin=subprocess.PIPE, text=True)
        write_hid(adb, {"id": 1, "command": "register", "name": "Magic Remote Bridge",
                        "vid": 51966, "pid": 1, "bus": "usb", "descriptor": descriptor})
        time.sleep(1)
        for message in stream:
            if "report" in message:
                report = message["report"]
                if report[1] or report[2]:
                    pointer_selection = True
                down = bool(report[0] & 1)
                if args.tap_under_pointer:
                    report[0] &= ~1
                write_hid(adb, {"id": 1, "command": "report", "report": report})
                if args.tap_under_pointer and down and not pressed:
                    tap_pointer(args.adb_serial, args.adb, ime_helper, pointer_selection,
                                shell_session, ime_daemon)
                pressed = down
            elif "android_key" in message:
                if message["android_key"] in (19, 20, 21, 22):
                    pointer_selection = False
                subprocess.run([args.adb, "-s", args.adb_serial, "shell", "input", "keyevent",
                                str(message["android_key"])], check=True, timeout=5)
                print(f"Sent Android key {message['android_key']}.", flush=True)
            elif "error" in message:
                raise RuntimeError(message["error"])
            elif "grab_finished" in message:
                print("Exclusive input test finished.", flush=True)
                break
            elif "lg_control" in message:
                print("Remote control: LG" if message["lg_control"] else "Remote control: Chromecast", flush=True)
        else:
            raise RuntimeError("TV input stream closed")
    except KeyboardInterrupt:
        print("Stopping pointer bridge.", file=sys.stderr)
    finally:
        stop_lease.set()
        if ime_daemon is not None:
            ime_daemon.close()
        if shell_session is not None:
            shell_session.close()
        if adb is not None and adb.stdin and not adb.stdin.closed:
            adb.stdin.close()
        remote.terminate()
        for process in (remote, adb):
            if process is None:
                continue
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return 0


def stop_bridge(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_bridge)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
