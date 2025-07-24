#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Stylized script to display location, current time, and weather on a Waveshare 2.13" e-ink (V4), flipped 180°.
Fetches weather, timezone, and location every 30 minutes; updates display every minute synced to real clock.
Stores API key in a .env file.
Ensures minute updates use partial refresh without clearing location/weather, and weather updates trigger full refresh.
All output is rotated 180° for upside-down mounting.
"""
import sys
import os

# Add lib directory to sys.path for local modules/resources
dlib = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(dlib):
    sys.path.append(dlib)

import logging
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from waveshare_epd import epd2in13_V4
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Determine base directory and path to local font
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
FONT_PATH = os.path.join(BASE_DIR, 'lib', 'font', 'aktiv.ttf')

# Configuration
WEATHER_URL     = os.getenv("WEATHER_URL", "https://webfoundry.io/api/weather")
API_KEY         = os.getenv("API_KEY", "")
FETCH_INTERVAL  = 30 * 60  # seconds between weather+timezone+location fetches
UPDATE_INTERVAL = 60       # seconds between minute updates

# Development mode: if true, fetch data each minute (for testing)
DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "yes")
if DEV_MODE:
    logging.info("DEV_MODE enabled: fetching data every minute")
    FETCH_INTERVAL = UPDATE_INTERVAL

logging.basicConfig(level=logging.INFO)

# Fetch weather, timezone, and location every FETCH_INTERVAL
def fetch_data():
    try:
        params = {}
        if API_KEY:
            params['key'] = API_KEY
        full_url = requests.Request('GET', WEATHER_URL, params=params).prepare().url
        logging.info("Fetching data from URL: %s", full_url)
        r = requests.get(WEATHER_URL, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        loc = j.get("location", "Unknown").upper()
        tz_str = j.get("timezone") or "America/Vancouver"
        w = j["weather"]["data"]["weather"]
        desc = w.get("description", "N/A").upper()
        temp = w.get("temp", {}).get("cur")
        weather_text = f"{desc}, {temp:.1f}°C"
        return loc, weather_text, tz_str
    except Exception as e:
        logging.error("Data fetch failed: %s", e)
        return "UNKNOWN", "WEATHER UNAVAILABLE", None


def main():
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)

    # Load fonts
    if not os.path.exists(FONT_PATH):
        logging.error("Custom font not found at %s, falling back to default", FONT_PATH)
        font_loc = font_time = font_wthr = ImageFont.load_default()
    else:
        try:
            font_loc = ImageFont.truetype(FONT_PATH, 14)
            font_time = ImageFont.truetype(FONT_PATH, 80)
            font_wthr = ImageFont.truetype(FONT_PATH, 14)
        except Exception as e:
            logging.error("Font load failed: %s", e)
            font_loc = font_time = font_wthr = ImageFont.load_default()

    # Initial data fetch and full refresh
    location, weather_text, tz_str = fetch_data()
    timezone_str = tz_str or "America/Vancouver"
    last_fetch = time.time()

    def draw_full():
        # Create non-rotated buffer
        raw = Image.new('1', (epd.height, epd.width), 255)
        d = ImageDraw.Draw(raw)
        # Location top
        w, h = d.textsize(location, font=font_loc)
        d.text(((epd.height-w)//2, 5), location, font=font_loc, fill=0)
        # Time center
        now = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
        w, h = d.textsize(now, font=font_time)
        d.text(((epd.height-w)//2, (epd.width-h)//2 - 10), now, font=font_time, fill=0)
        # Weather bottom
        w, h = d.textsize(weather_text, font=font_wthr)
        d.text(((epd.height-w)//2, epd.width-h-5), weather_text, font=font_wthr, fill=0)
        # Rotate entire buffer for display
        rotated = raw.rotate(180)
        return raw, rotated

    # Get raw and rotated full images
    raw_full, full_img = draw_full()
    epd.display(epd.getbuffer(full_img))
    logging.info("Full refresh completed.")

    # Setup partial base to rotated full image
    epd.displayPartBaseImage(epd.getbuffer(full_img))

    # Calculate time region on raw image, then transform coords for rotated
    sample = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
    d_bbox = ImageDraw.Draw(raw_full)
    tw, th = d_bbox.textsize(sample, font=font_time)
    # Raw coords
    raw_tx = (epd.height - tw)//2
    raw_ty = (epd.width - th)//2 - 10
    # Rotated coords: rotate rectangle by 180° around center
    time_box = (raw_tx, raw_ty, raw_tx+tw, raw_ty+th)
    # For rotated image 180°, the time box remains same
    tx, ty = raw_tx, raw_ty

    # Main loop
    while True:
        # Sync to next minute
        now_ts = time.time()
        time.sleep(UPDATE_INTERVAL - (now_ts % UPDATE_INTERVAL))

        # Partial update: copy rotated full image, clear time region, redraw time
        now = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
        time_img = full_img.copy()
        td = ImageDraw.Draw(time_img)
        td.rectangle(time_box, fill=255)
        td.text((tx, ty), now, font=font_time, fill=0)
        epd.displayPartial(epd.getbuffer(time_img))
        logging.info("Partial time update: %s", now)

        # Full refresh on interval
        if time.time() - last_fetch >= FETCH_INTERVAL:
            location, weather_text, tz_new = fetch_data()
            if tz_new:
                timezone_str = tz_new
            last_fetch = time.time()
            raw_full, full_img = draw_full()
            epd.init()
            epd.Clear(0xFF)
            epd.display(epd.getbuffer(full_img))
            logging.info("Full refresh after fetch.")
            epd.displayPartBaseImage(epd.getbuffer(full_img))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logging.error("Fatal error: %s", e)
        sys.exit(1)
