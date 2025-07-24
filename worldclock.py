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

try:
    logging.info("epd7in5_V2 Demo")
    epd = epd7in5_V2.EPD()

    logging.info("init and Clear")
    epd.init_fast()
    epd.Clear()

    #print(f"Display Width: {epd.width}, Display height: {epd.height}")
    # Display Width: 800, Display height: 480
    # Create a blank image
    Himage = Image.new('1', (epd.width, epd.height), 255) #255: white, clear the frame
    draw = ImageDraw.Draw(Himage)

#Drawing function Argyments:
# draw.rectangle((x1, y1, x2, y2), outline=0, fill=None)
# draw.arc((x1, y1, x2, y2),startAngle, endAngle, fill=0), (x1, y1, x2, y2) bounding box of the ellipse that the arc is part of
# draw.chord((x1, y1, x2, y2), startAngle, endAngle, outline=0, fill=None), different to arc as it will close the shape and allow fill colour
# draw.line((x1, y1, x2, y2), fill=0, width=1)

    while True:
        #Generate a random pattern
        draw.rectangle((random.randint(10,epd.width-10), random.randint(10,epd.height-10), random.randint(10,epd.width-10), random.randint(10,epd.height-10)), outline=0)

        #Display the generated image
        epd.display(epd.getbuffer(Himage))

        #Hold the frame for 2 seconds
        time.sleep(2)

#     logging.info("Goto Sleep...")
#     epd.sleep()

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5_V2.epdconfig.module_exit(cleanup=True)
    exit()