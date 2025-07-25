#!/usr/bin/env python3
# display_debug.py

import sys, os, logging

dlib = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(dlib):
    sys.path.append(dlib)

from waveshare_epd import epd2in13_V4
from PIL import Image, ImageDraw, ImageFont

# make sure libdir is on sys.path
BASE = os.path.dirname(os.path.realpath(__file__))
LIBDIR = os.path.join(BASE, 'lib')
if os.path.exists(LIBDIR):
    sys.path.append(LIBDIR)

def show(msg):
    # init
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)
    # pick a font (you already have an aktiv.ttf in lib/font)
    font_path = os.path.join(LIBDIR, 'font', 'aktiv.ttf')
    if os.path.exists(font_path):
        font = ImageFont.truetype(font_path, 16)
    else:
        font = ImageFont.load_default()
    # canvas
    img = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(img)
    # wrap & draw
    lines = []
    for line in msg.split('\n'):
        # simple wrap at 20 chars
        while len(line) > 20:
            lines.append(line[:20])
            line = line[20:]
        lines.append(line)
    y = 5
    for ln in lines[: (epd.width // 16) ]:  # limit to fit
        w, h = draw.textsize(ln, font=font)
        draw.text(((epd.height-w)//2, y), ln, font=font, fill=0)
        y += h + 2
    # display
    epd.display(epd.getbuffer(img))
    epd.sleep()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        show(" ".join(sys.argv[1:]))
    else:
        # read from stdin
        show(sys.stdin.read())