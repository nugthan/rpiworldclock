#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Stylized script to display location, current time, and weather on a Waveshare 2.13" e-ink (V4).
Fetches weather, timezone, and location every 30 minutes; updates display every minute synced to real clock.
Stores API key in a .env file.
Ensures the minute updates use partial refresh, and weather updates trigger full refresh.
"""
import sys
import os

# Add lib directory to sys.path for local modules/resources
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

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
        # Extract location
        loc = j.get("location", "Unknown").upper()
        # Extract timezone
        tz_str = j.get("timezone") or "America/Vancouver"
        # Extract weather
        w = j["weather"]["data"]["weather"]
        desc = w.get("description", "N/A").upper()
        temp = w.get("temp", {}).get("cur")
        weather_text = f"{desc}, {temp:.1f}°C"
        return loc, weather_text, tz_str
    except Exception as e:
        logging.error("Data fetch failed: %s", e)
        return "UNKNOWN", "WEATHER UNAVAILABLE", None


def main():
    # Initialize display
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)

    # Load fonts
    if not os.path.exists(FONT_PATH):
        logging.error("Custom font not found at %s, falling back to default font", FONT_PATH)
        font_loc = ImageFont.load_default()
        font_time = ImageFont.load_default()
        font_wthr = ImageFont.load_default()
    else:
        try:
            font_loc = ImageFont.truetype(FONT_PATH, 14)
            font_time = ImageFont.truetype(FONT_PATH, 80)
            font_wthr = ImageFont.truetype(FONT_PATH, 14)
        except Exception as e:
            logging.error("Failed to load custom font %s: %s", FONT_PATH, e)
            font_loc = ImageFont.load_default()
            font_time = ImageFont.load_default()
            font_wthr = ImageFont.load_default()

    # Initial data fetch
    location, weather_text, tz_str = fetch_data()
    timezone_str = tz_str or "America/Vancouver"
    last_fetch = time.time()

    # Function to draw full refresh image
    def draw_full():
        tz = ZoneInfo(timezone_str)
        now = datetime.now(tz).strftime("%H:%M").upper()
        img_full = Image.new('1', (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(img_full)
        # Location
        w, h = draw.textsize(location, font=font_loc)
        draw.text(((epd.height - w)//2, 5), location, font=font_loc, fill=0)
        # Time
        w, h = draw.textsize(now, font=font_time)
        draw.text(((epd.height - w)//2, (epd.width - h)//2 - 10), now, font=font_time, fill=0)
        # Weather
        w, h = draw.textsize(weather_text, font=font_wthr)
        draw.text(((epd.height - w)//2, epd.width - h - 5), weather_text, font=font_wthr, fill=0)
        return img_full

    # Perform initial full refresh
    full_img = draw_full()
    epd.display(epd.getbuffer(full_img))
    logging.info("Performed full refresh.")

    # Prepare partial update canvas
    img_partial = Image.new('1', (epd.height, epd.width), 255)
    draw_partial = ImageDraw.Draw(img_partial)
    epd.displayPartBaseImage(epd.getbuffer(img_partial))

    # Calculate time text box coords
    tz = ZoneInfo(timezone_str)
    sample_time = datetime.now(tz).strftime("%H:%M").upper()
    tw, th = draw_partial.textsize(sample_time, font=font_time)
    tx = (epd.height - tw)//2
    ty = (epd.width - th)//2 - 10
    time_box = (tx, ty, tx + tw, ty + th)

    # Main loop: partial updates for time, full for data
    while True:
        # Sync to next minute
        now_ts = time.time()
        sleep_secs = UPDATE_INTERVAL - (now_ts % UPDATE_INTERVAL)
        time.sleep(sleep_secs)

        # Partial update time
        tz = ZoneInfo(timezone_str)
        now = datetime.now(tz).strftime("%H:%M").upper()
        # Clear previous time
        draw_partial.rectangle(time_box, fill=255)
        # Draw new time
        draw_partial.text((tx, ty), now, font=font_time, fill=0)
        epd.displayPartial(epd.getbuffer(img_partial))
        logging.info("Partial time update: %s", now)

        # Full refresh when FETCH_INTERVAL elapsed
        if time.time() - last_fetch >= FETCH_INTERVAL:
            location, weather_text, tz_new = fetch_data()
            if tz_new:
                timezone_str = tz_new
            last_fetch = time.time()
            full_img = draw_full()
            epd.init()
            epd.Clear(0xFF)
            epd.display(epd.getbuffer(full_img))
            logging.info("Performed full refresh after data fetch.")
            # Reset partial canvas
            img_partial = Image.new('1', (epd.height, epd.width), 255)
            draw_partial = ImageDraw.Draw(img_partial)
            epd.displayPartBaseImage(epd.getbuffer(img_partial))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logging.error("Fatal error: %s", e)
        sys.exit(1)
