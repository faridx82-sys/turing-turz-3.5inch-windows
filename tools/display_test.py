#!/usr/bin/env python3
"""Paint a bright test pattern on a Turing / TURZX 3.5" USB display.

This bypasses the dashboard and talks to the panel directly. It is handy to
verify the cable, the COM port and the protocol before installing the service.

Usage:
    python tools/display_test.py
    python tools/display_test.py --port COM3
    python tools/display_test.py --baud 115200 --chunk-rows 4

Requires: pyserial, pillow
"""

import argparse
import time

import serial
from PIL import Image, ImageDraw, ImageFont
from serial.tools import list_ports

VID = 0x1A86
PID = 0x5722

CMD_CLEAR = 102
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197

ORIENTATION_PORTRAIT = 0
ORIENTATION_LANDSCAPE = 2

WIDTH, HEIGHT = 480, 320


def find_port():
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def encode_coords(x0, y0, x1, y1):
    buf = bytearray(6)
    buf[0] = x0 >> 2
    buf[1] = ((x0 & 3) << 6) + (y0 >> 4)
    buf[2] = ((y0 & 15) << 4) + (x1 >> 6)
    buf[3] = ((x1 & 63) << 2) + (y1 >> 8)
    buf[4] = y1 & 255
    return buf


def send_command(ser, cmd, x=0, y=0, ex=0, ey=0):
    buf = encode_coords(x, y, ex, ey)
    buf[5] = cmd
    ser.write(bytes(buf))
    ser.flush()


def set_orientation(ser, orientation, width, height):
    buf = bytearray(16)
    buf[5] = CMD_SET_ORIENTATION
    buf[6] = orientation + 100
    buf[7] = (width >> 8) & 0xFF
    buf[8] = width & 0xFF
    buf[9] = (height >> 8) & 0xFF
    buf[10] = height & 0xFF
    ser.write(bytes(buf))
    ser.flush()


def to_rgb565(img):
    pixels = img.convert("RGB").tobytes()
    out = bytearray(len(pixels) // 3 * 2)
    for i in range(len(pixels) // 3):
        r, g, b = pixels[i * 3], pixels[i * 3 + 1], pixels[i * 3 + 2]
        value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[i * 2] = value & 0xFF
        out[i * 2 + 1] = (value >> 8) & 0xFF
    return bytes(out)


def make_image():
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 180, 60))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 60)
    except Exception:
        font = ImageFont.load_default()
    draw.text((WIDTH // 2, HEIGHT // 2), "HELLO", fill=(255, 255, 255), font=font, anchor="mm")
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=(255, 255, 255), width=6)
    return img


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port (default: auto-detect)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--chunk-rows", type=int, default=4)
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        raise SystemExit("Display not found (VID_1A86 / PID_5722). Check the USB cable.")

    print(f"port={port} baud={args.baud} chunk_rows={args.chunk_rows}", flush=True)

    # RTS/CTS hardware flow control is mandatory: without it the panel drops
    # frames and stays blank.
    with serial.Serial(port, args.baud, timeout=2, rtscts=True) as ser:
        ser.reset_input_buffer()

        send_command(ser, CMD_SCREEN_ON)
        time.sleep(0.3)
        send_command(ser, CMD_SET_BRIGHTNESS, 0)  # 0 = maximum brightness
        time.sleep(0.3)

        # The panel only clears correctly in its native portrait orientation.
        set_orientation(ser, ORIENTATION_PORTRAIT, 320, 480)
        time.sleep(0.2)
        send_command(ser, CMD_CLEAR)
        time.sleep(0.5)

        set_orientation(ser, ORIENTATION_LANDSCAPE, WIDTH, HEIGHT)
        time.sleep(0.5)

        image = make_image()
        data = to_rgb565(image)
        print(f"sending {len(data)} bytes", flush=True)
        send_command(ser, CMD_DISPLAY_BITMAP, 0, 0, WIDTH - 1, HEIGHT - 1)
        time.sleep(0.02)

        chunk = WIDTH * 2 * args.chunk_rows
        for offset in range(0, len(data), chunk):
            ser.write(data[offset:offset + chunk])
            ser.flush()
            time.sleep(0.005)

    print("done - the image stays on the panel after the port closes", flush=True)


if __name__ == "__main__":
    main()
