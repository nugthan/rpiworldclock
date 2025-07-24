#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Stylized script to display location, current time, and weather on a Waveshare 2.13" e-ink (V4), flipped 180°.
Fetches weather, timezone, and location every 30 minutes; updates display every minute synced to real clock.
Stores API key in a .env file.
Ensures minute updates use partial refresh without clearing location/weather, and weather updates trigger full refresh.
All output is correctly rotated 180° for upside-down mounting, including partial refreshes.
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

    # Initial data fetch and images
    location, weather_text, tz_str = fetch_data()
    timezone_str = tz_str or "America/Vancouver"
    last_fetch = time.time()

    # Draw full images (raw and rotated)
    def draw_full_images():
        # Create raw buffer (unrotated)
        raw = Image.new('1', (epd.height, epd.width), 255)
        d = ImageDraw.Draw(raw)
        # Location top
        w, h = d.textsize(location, font=font_loc)
        d.text(((epd.height-w)//2, 5), location, font=font_loc, fill=0)
        # Time center
        now_str = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
        w, h = d.textsize(now_str, font=font_time)
        d.text(((epd.height-w)//2, (epd.width-h)//2 - 10), now_str, font=font_time, fill=0)
        # Weather bottom
        w, h = d.textsize(weather_text, font=font_wthr)
        d.text(((epd.height-w)//2, epd.width-h-5), weather_text, font=font_wthr, fill=0)
        # Create rotated display image
        rotated = raw.rotate(180)
        return raw, rotated

    raw_full, full_img = draw_full_images()
    epd.display(epd.getbuffer(full_img))
    logging.info("Full refresh completed.")

    # Setup partial base as the rotated full image
    epd.displayPartBaseImage(epd.getbuffer(full_img))

    # Calculate time region on raw image
    sample_time = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
    d_sample = ImageDraw.Draw(raw_full)
    tw, th = d_sample.textsize(sample_time, font=font_time)
    raw_tx = (epd.height - tw)//2
    raw_ty = (epd.width - th)//2 - 10
    time_box = (raw_tx, raw_ty, raw_tx+tw, raw_ty+th)

    # Main loop: partial time and full data refresh
    while True:
        # Sync to next minute
        now_ts = time.time()
        time.sleep(UPDATE_INTERVAL - (now_ts % UPDATE_INTERVAL))

        # Partial update: use raw_full as base, clear time region, draw new time, then rotate
        now_str = datetime.now(ZoneInfo(timezone_str)).strftime("%H:%M").upper()
        raw_partial = raw_full.copy()
        dp = ImageDraw.Draw(raw_partial)
        dp.rectangle(time_box, fill=255)
        dp.text((raw_tx, raw_ty), now_str, font=font_time, fill=0)
        img_partial = raw_partial.rotate(180)
        epd.displayPartial(epd.getbuffer(img_partial))
        logging.info("Partial time update: %s", now_str)

        # Full refresh on interval
        if time.time() - last_fetch >= FETCH_INTERVAL:
            location, weather_text, tz_new = fetch_data()
            if tz_new:
                timezone_str = tz_new
            last_fetch = time.time()
            raw_full, full_img = draw_full_images()
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
