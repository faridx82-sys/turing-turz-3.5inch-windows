#!/usr/bin/env python3
"""
Turing / TURZX 3.5" USB System Monitor - Windows 11 service
https://github.com/faridx82-sys/turing-turz-3.5inch-windows
Based on https://github.com/faridx82-sys/turing-turz-3.5inch (GPL-3.0)

Protocol: 6-byte command packets, RGB565 image data, 115200 baud, RTS/CTS flow control
Native panel: 320x480 portrait; rendered in landscape (480x320)

Usage:
    python monitor_win.py                     # run on the display (auto-detect COM port)
    python monitor_win.py COM3                # run on a specific port
    python monitor_win.py --preview out.png   # render one frame to PNG, no serial

For service installation run setup.ps1 from an elevated PowerShell.
"""

import os
import sys
import time
import tempfile
import struct
import shutil
import socket
import logging
import subprocess
from datetime import datetime
from logging.handlers import RotatingFileHandler

import serial
from serial.tools import list_ports
from PIL import Image, ImageDraw, ImageFont

import psutil


def _log_dir():
    """Pick a writable log directory (service runs as SYSTEM)."""
    candidates = [
        os.environ.get("TURING_LOG_DIR"),
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "TuringDashboard"),
        os.path.join(tempfile.gettempdir(), "TuringDashboard"),
    ]
    for c in candidates:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            probe = os.path.join(c, ".write-test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return c
        except Exception:
            continue
    return "."


LOG_DIR = _log_dir()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.join(LOG_DIR, "monitor.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("turing-display")

CMD_RESET = 101
CMD_CLEAR = 102
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197

ORIENTATION_PORTRAIT = 0
ORIENTATION_LANDSCAPE = 2

DISPLAY_WIDTH = 320
DISPLAY_HEIGHT = 480
BAUD_RATE = 115200
VID = 0x1A86
PID = 0x5722
SERIAL_ID = "USB35INCHIPSV2"


class TuringDisplay:
    def __init__(self, port: str = "AUTO"):
        self.port = port
        self.ser = None
        self.orientation = ORIENTATION_PORTRAIT

    def auto_detect_port(self):
        for p in list_ports.comports():
            if p.serial_number == SERIAL_ID:
                return p.device
            if p.vid == VID and p.pid == PID:
                return p.device
        return None

    def open(self):
        if self.port == "AUTO":
            detected = self.auto_detect_port()
            if not detected:
                log.error("Display not found. Check the USB cable.")
                raise serial.SerialException("display not found")
            self.port = detected
            log.info(f"Auto-detected display on {self.port}")
        self.ser = serial.Serial(self.port, BAUD_RATE, timeout=2, rtscts=True)
        log.info(f"Connected to {self.port}")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    @staticmethod
    def _encode_coords(x0, y0, x1, y1):
        buf = bytearray(6)
        buf[0] = (x0 >> 2)
        buf[1] = (((x0 & 3) << 6) + (y0 >> 4))
        buf[2] = (((y0 & 15) << 4) + (x1 >> 6))
        buf[3] = (((x1 & 63) << 2) + (y1 >> 8))
        buf[4] = (y1 & 255)
        return buf

    def send_command(self, cmd, x=0, y=0, ex=0, ey=0):
        buf = self._encode_coords(x, y, ex, ey)
        buf[5] = cmd
        self.ser.write(bytes(buf))

    def set_brightness(self, level):
        level = max(0, min(100, level))
        abs_level = int(255 - (level / 100) * 255)
        self.send_command(CMD_SET_BRIGHTNESS, abs_level)

    def set_orientation(self, orientation=ORIENTATION_PORTRAIT):
        self.orientation = orientation
        w, h = self._dimensions()
        buf = bytearray(16)
        buf[5] = CMD_SET_ORIENTATION
        buf[6] = orientation + 100
        buf[7] = (w >> 8) & 0xFF
        buf[8] = w & 0xFF
        buf[9] = (h >> 8) & 0xFF
        buf[10] = h & 0xFF
        self.ser.write(bytes(buf))

    def _dimensions(self):
        if self.orientation in (ORIENTATION_PORTRAIT, 1):
            return DISPLAY_WIDTH, DISPLAY_HEIGHT
        return DISPLAY_HEIGHT, DISPLAY_WIDTH

    def screen_on(self):
        self.send_command(CMD_SCREEN_ON)

    def clear(self):
        # Clear only works correctly in portrait on these panels
        self.set_orientation(ORIENTATION_PORTRAIT)
        time.sleep(0.2)
        self.send_command(CMD_CLEAR)
        time.sleep(0.4)
        self.set_orientation(ORIENTATION_LANDSCAPE)
        time.sleep(0.4)

    def send_image(self, img):
        w, h = self._dimensions()
        if img.size != (w, h):
            img = img.resize((w, h))
        self.send_command(CMD_DISPLAY_BITMAP, 0, 0, w - 1, h - 1)
        time.sleep(0.01)
        rgb565 = self._image_to_rgb565(img)
        chunk_size = w * 8  # 4 rows, same as reference library
        for i in range(0, len(rgb565), chunk_size):
            self.ser.write(rgb565[i:i + chunk_size])
            self.ser.flush()
            time.sleep(0.002)

    @staticmethod
    def _image_to_rgb565(img):
        pixels = img.convert("RGB").tobytes()
        result = bytearray(len(pixels) // 3 * 2)
        for i in range(len(pixels) // 3):
            r, g, b = pixels[i * 3], pixels[i * 3 + 1], pixels[i * 3 + 2]
            val = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            struct.pack_into("<H", result, i * 2, val)
        return bytes(result)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


class SystemStats:
    _cpu_temp = None
    _cpu_temp_ts = 0.0
    _cpu_temp_warned = False
    _cpu_temp_logged = False

    @staticmethod
    def hostname():
        try:
            return socket.gethostname()
        except Exception:
            return "unknown"

    @staticmethod
    def uptime():
        try:
            secs = time.time() - psutil.boot_time()
            days, rem = divmod(int(secs), 86400)
            hours, rem = divmod(rem, 3600)
            mins = rem // 60
            return (f"{days}d" if days else "") + f"{hours}h{mins}m"
        except Exception:
            return "?"

    @staticmethod
    def cpu_percent():
        try:
            return psutil.cpu_percent(interval=0.5)
        except Exception:
            return 0.0

    @staticmethod
    def cpu_freq():
        try:
            f = psutil.cpu_freq()
            return f.current / 1000.0 if f and f.current else None
        except Exception:
            return None

    @staticmethod
    def cpu_temp():
        """CPU package temperature via LibreHardwareMonitor's library (needs admin/SYSTEM)."""
        now = time.time()
        if now - SystemStats._cpu_temp_ts < 30:
            return SystemStats._cpu_temp
        SystemStats._cpu_temp_ts = now
        SystemStats._cpu_temp = None
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lhm_cpu_temp.ps1")
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
        )
        try:
            r = subprocess.run(
                [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = r.stdout.strip()
            if r.returncode == 0 and out:
                value = float(out.splitlines()[-1].replace(",", "."))
                if value > 0:
                    SystemStats._cpu_temp = value
                    if not SystemStats._cpu_temp_logged:
                        log.info(f"CPU temperature source OK: {SystemStats._cpu_temp} C")
                        SystemStats._cpu_temp_logged = True
                elif not SystemStats._cpu_temp_warned:
                    log.warning("CPU temp helper returned no reading (driver not available?)")
                    SystemStats._cpu_temp_warned = True
            elif not SystemStats._cpu_temp_warned:
                log.warning(f"CPU temp helper failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
                SystemStats._cpu_temp_warned = True
        except Exception as e:
            if not SystemStats._cpu_temp_warned:
                log.warning(f"CPU temp helper error: {e}")
                SystemStats._cpu_temp_warned = True
        return SystemStats._cpu_temp

    @staticmethod
    def ram():
        try:
            vm = psutil.virtual_memory()
            return vm.used, vm.total, vm.percent
        except Exception:
            return 0, 1, 0

    @staticmethod
    def disk():
        try:
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            du = psutil.disk_usage(drive)
            return du.used, du.total, du.percent
        except Exception:
            return 0, 1, 0

    @staticmethod
    def net():
        try:
            n = psutil.net_io_counters()
            return n.bytes_recv, n.bytes_sent
        except Exception:
            return 0, 0

    @staticmethod
    def disk_io():
        try:
            d = psutil.disk_io_counters()
            return (d.read_bytes, d.write_bytes) if d else (0, 0)
        except Exception:
            return 0, 0

    @staticmethod
    def gpu_stats():
        exe = shutil.which("nvidia-smi")
        if not exe:
            cand = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
            exe = cand if os.path.exists(cand) else None
        if not exe:
            return []
        try:
            r = subprocess.run(
                [exe, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = []
            for line in r.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    out.append({
                        "gpu_util": int(float(parts[0])),
                        "mem_used": int(float(parts[1])),
                        "mem_total": int(float(parts[2])),
                        "temp": int(float(parts[3])),
                    })
            return out
        except Exception:
            return []


class DashboardRenderer:
    def __init__(self, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
        self.width = width
        self.height = height
        self.font_path = self._find_font()

    @staticmethod
    def _find_font():
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates = [
            os.path.join(windir, "Fonts", "segoeuib.ttf"),
            os.path.join(windir, "Fonts", "arialbd.ttf"),
            os.path.join(windir, "Fonts", "segoeui.ttf"),
            os.path.join(windir, "Fonts", "arial.ttf"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def _font(self, size):
        if self.font_path:
            return ImageFont.truetype(self.font_path, size)
        return ImageFont.load_default()

    def render(self, stats):
        W, H = self.width, self.height
        img = Image.new("RGB", (W, H), (18, 18, 28))
        draw = ImageDraw.Draw(img)

        font_pct = self._font(28)
        font_lg = self._font(22)
        font_md = self._font(14)
        font_sm = self._font(11)
        font_xs = self._font(9)

        # Title bar
        hostname = stats.hostname().split(".")[0]
        draw.rectangle([0, 0, W, 26], fill=(30, 40, 60))
        draw.text((W // 2, 13), hostname, fill=(180, 210, 255), font=font_sm, anchor="mm")
        draw.text((W - 6, 13), stats.uptime(), fill=(130, 150, 180), font=font_xs, anchor="rm")

        COL = W // 2
        cpu_pct = stats.cpu_percent()
        cpu_temp = stats.cpu_temp()
        cpu_freq = stats.cpu_freq()
        gpus = stats.gpu_stats()
        ram_used, ram_total, ram_pct = stats.ram()
        disk_used, disk_total, disk_pct = stats.disk()

        rx1, tx1 = stats.net()
        time.sleep(2)
        rx2, tx2 = stats.net()
        rx_rate = (rx2 - rx1) / (2 * 1024)
        tx_rate = (tx2 - tx1) / (2 * 1024)

        def fmt_speed(kbps):
            if kbps >= 1024 * 1024:
                return f"{kbps / 1024 / 1024:.1f}G"
            if kbps >= 1024:
                return f"{kbps / 1024:.1f}M"
            return f"{kbps:.0f}K"

        def row(cy, label, pct, detail, left, bar_fg):
            draw.text((left + 8, cy + 6), label, fill=(255, 255, 255), font=font_md, anchor="la")
            draw.text((left + COL - 8, cy - 2), f"{pct:.0f}%", fill=(255, 255, 255), font=font_pct, anchor="ra")
            by = cy + 34
            bw = COL - 16
            draw.rounded_rectangle([left + 8, by, left + 8 + bw, by + 10], radius=3, fill=(40, 50, 70))
            fw = max(4, int(bw * min(pct, 100) / 100))
            draw.rounded_rectangle([left + 8, by, left + 8 + fw, by + 10], radius=3, fill=bar_fg)
            draw.text((left + 8, by + 14), detail, fill=(140, 155, 180), font=font_sm, anchor="la")

        r = [38, 100, 162, 220]

        # Row 1: CPU + GPU
        cpu_detail = f"{cpu_freq:.1f}GHz" if cpu_freq is not None else f"{psutil.cpu_count()} cores"
        row(r[0], "CPU", cpu_pct, cpu_detail, 0, (60, 180, 120))

        if gpus:
            g = gpus[0]
            mem_pct = (g["mem_used"] / max(g["mem_total"], 1)) * 100
            row(r[0], "GPU", g["gpu_util"],
                f"{g['temp']}\u00b0C  VRAM {g['mem_used']}/{g['mem_total']}M ({mem_pct:.0f}%)",
                COL, (100, 160, 220))
        else:
            draw.text((COL + 8, r[0]), "GPU", fill=(255, 255, 255), font=font_md)
            draw.text((COL + 8, r[0] + 22), "NVIDIA driver not found", fill=(100, 110, 130), font=font_sm)

        # Row 2: RAM + DISK
        row(r[1], "RAM", ram_pct,
            f"{ram_used / 1024 ** 3:.1f}/{ram_total / 1024 ** 3:.1f} GiB",
            0, (220, 180, 60))
        row(r[1], "DISK", disk_pct,
            f"{disk_used / 1024 ** 3:.1f}/{disk_total / 1024 ** 3:.1f} GiB",
            COL, (80, 160, 200))

        # Row 3: CPU + GPU temperature
        dy = r[2]
        draw.rectangle([6, dy, W - 6, dy + 48], fill=(22, 24, 36), outline=(40, 50, 70))
        draw.text((16, dy + 5), "TEMPERATURE", fill=(150, 165, 190), font=font_sm)
        cpu_t = f"{cpu_temp:.0f}\u00b0C" if cpu_temp is not None else "--\u00b0C"
        gpu_t = f"{gpus[0]['temp']}\u00b0C" if gpus else "--\u00b0C"
        draw.text((16, dy + 24), "CPU", fill=(255, 255, 255), font=font_sm)
        draw.text((54, dy + 19), cpu_t, fill=(60, 200, 120), font=font_lg)
        draw.text((COL + 16, dy + 24), "GPU", fill=(255, 255, 255), font=font_sm)
        draw.text((COL + 54, dy + 19), gpu_t, fill=(100, 160, 220), font=font_lg)

        # Row 4: NETWORK
        ny = r[3]
        draw.rectangle([6, ny, W - 6, ny + 48], fill=(22, 24, 36), outline=(40, 50, 70))
        draw.text((16, ny + 6), "NETWORK", fill=(255, 255, 255), font=font_md)
        draw.text((16, ny + 26), f"\u25bc {fmt_speed(rx_rate)}/s", fill=(60, 200, 100), font=font_md)
        draw.text((COL + 16, ny + 26), f"\u25b2 {fmt_speed(tx_rate)}/s", fill=(100, 180, 255), font=font_md)
        draw.text((W - 16, ny + 6), f"rcvd {fmt_speed(rx2 / 1024)}", fill=(100, 120, 140), font=font_sm, anchor="ra")

        # Bottom bar
        now = datetime.now().strftime("%H:%M:%S")
        draw.rectangle([0, H - 22, W, H], fill=(30, 40, 60))
        draw.text((8, H - 11), now, fill=(100, 130, 160), font=font_sm, anchor="lm")

        return img


def main():
    args = [a for a in sys.argv[1:]]
    preview = None
    if "--preview" in args:
        i = args.index("--preview")
        preview = args[i + 1] if len(args) > i + 1 else "preview.png"
        args = args[:i] + args[i + 2:]

    port = args[0] if args else "AUTO"
    renderer = DashboardRenderer(width=DISPLAY_HEIGHT, height=DISPLAY_WIDTH)

    if preview:
        img = renderer.render(SystemStats())
        img.save(preview)
        log.info(f"Preview written to {preview}")
        return

    while True:
        try:
            with TuringDisplay(port) as display:
                display.screen_on()
                time.sleep(0.3)
                display.set_brightness(60)
                time.sleep(0.3)
                display.clear()
                log.info("Starting system monitor loop...")
                while True:
                    img = renderer.render(SystemStats())
                    display.send_image(img)
                    log.info("frame sent")
        except serial.SerialException as e:
            log.error(f"Serial error: {e}. Reconnecting in 10s...")
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
