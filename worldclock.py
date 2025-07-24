#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
picdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'pic')
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')


if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd2in13_V4
import time
from PIL import Image,ImageDraw,ImageFont
import traceback

logging.basicConfig(level=logging.DEBUG)

def main():
    try:
        # Initialize and clear the display
        epd = epd2in13_V4.EPD()
        epd.init()
        epd.Clear(0xFF)

        # Get current Vancouver time
        tz = ZoneInfo("America/Vancouver")
        now = datetime.now(tz).strftime("%H:%M")

        # Create a blank image (height x width) and drawing context
        img = Image.new('1', (epd.height, epd.width), 255)  # 255: white background
        draw = ImageDraw.Draw(img)

        # Load a built-in font
        font = ImageFont.load_default()

        # Calculate text position to center it
        w, h = draw.textsize(now, font=font)
        x = (epd.height - w) // 2
        y = (epd.width - h) // 2

        # Draw the time string
        draw.text((x, y), now, font=font, fill=0)  # 0: black

        # Display the image buffer and sleep
        epd.display(epd.getbuffer(img))
        logging.info(f"Displayed Vancouver time: {now}")
        epd.sleep()

    except Exception as e:
        logging.error("Error updating display: %s", e)
        sys.exit(1)

# Entry point
if __name__ == "__main__":
    main()
