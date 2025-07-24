#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Stylized script to display location, current time, and weather on a Waveshare 2.13" e-ink (V4).
Fetches weather, timezone, and location every 30 minutes; updates display every minute synced to real clock.
Stores API key in a .env file.
Ensure SPI is enabled and `waveshare_epd`, `requests`, and `python-dotenv` are installed.
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
FONT_PATH = os.path.join(BASE_DIR, 'lib', 'font', 'aktiv.otf')

# Configuration
WEATHER_URL     = os.getenv("WEATHER_URL", "https://webfoundry.io/api/weather")
API_KEY         = os.getenv("API_KEY", "")
FETCH_INTERVAL  = 30 * 60  # 30 minutes
UPDATE_INTERVAL = 60       # 1 minute

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
        weather_text = f"{desc}, {temp:.1f}°C".upper()
        return loc, weather_text, tz_str
    except Exception as e:
        logging.error("Data fetch failed: %s", e)
        return "UNKNOWN", "WEATHER UNAVAILABLE", None


def main():
    # Initialize display
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)

    # Load fonts, as before
    if not os.path.exists(FONT_PATH):
        logging.error("Custom font not found at %s, falling back to default font", FONT_PATH)
        font_loc = font_time = font_wthr = ImageFont.load_default()
    else:
        try:
            font_loc = ImageFont.truetype(FONT_PATH, 20)
            # Even larger time font for prominence
            font_time = ImageFont.truetype(FONT_PATH, 120)
            font_wthr = ImageFont.truetype(FONT_PATH, 18)
        except Exception as e:
            logging.error("Failed to load custom font %s: %s", FONT_PATH, e)
            font_loc = font_time = font_wthr = ImageFont.load_default()

    # Initial data fetch (weather, timezone, location)
    location, weather_text, tz_new = fetch_data()
    timezone_str = tz_new or "America/Vancouver"
    last_fetch = time.time()

    # Draw full image (full refresh) with location, time, weather
    def draw_full():
        # Determine time
        tz = ZoneInfo(timezone_str)
        now = datetime.now(tz).strftime("%H:%M").upper()
        # Create full canvas
        full = Image.new('1', (epd.height, epd.width), 255)
        d = ImageDraw.Draw(full)
        # Location
        w, h = d.textsize(location, font=font_loc)
        d.text(((epd.height - w)//2, 5), location, font=font_loc, fill=0)
        # Time
        w, h = d.textsize(now, font=font_time)
        d.text(((epd.height - w)//2, (epd.width - h)//2 - 10), now, font=font_time, fill=0)
        # Weather
        w, h = d.textsize(weather_text, font=font_wthr)
        d.text(((epd.height - w)//2, epd.width - h - 5), weather_text, font=font_wthr, fill=0)
        return full

    # Perform initial full refresh
    full_img = draw_full()
    epd.display(epd.getbuffer(full_img))
    logging.info("Full refresh displayed.")

    # Prepare for partial updates: blank canvas and base image
    time_image = Image.new('1', (epd.height, epd.width), 255)
    time_draw = ImageDraw.Draw(time_image)
    epd.displayPartBaseImage(epd.getbuffer(time_image))

    # Define time region for clearing: use bounding box of time text
    tz = ZoneInfo(timezone_str)
    initial_time = datetime.now(tz).strftime("%H:%M").upper()
    tw, th = time_draw.textsize(initial_time, font=font_time)
    tx = (epd.height - tw)//2
    ty = (epd.width - th)//2 - 10
    time_box = (tx, ty, tx + tw, ty + th)

    # Loop: partial update every minute, full refresh every FETCH_INTERVAL
    while True:
        # Sleep to next minute boundary
        now_ts = time.time()
        sleep_secs = UPDATE_INTERVAL - (now_ts % UPDATE_INTERVAL)
        time.sleep(sleep_secs)

        # Time for partial update
        tz = ZoneInfo(timezone_str)
        now = datetime.now(tz).strftime("%H:%M").upper()
        # Clear previous time region
        time_draw.rectangle(time_box, fill=255)
        # Draw new time
        time_draw.text((tx, ty), now, font=font_time, fill=0)
        epd.displayPartial(epd.getbuffer(time_image))
        logging.info("Partial update: %s", now)

        # Check if need full refresh (weather + timezone)
        if time.time() - last_fetch >= FETCH_INTERVAL:
            # Fetch new weather & timezone
            loc, wtxt, tz_new = fetch_data()
            if loc: location = loc
            if tz_new: timezone_str = tz_new
            weather_text = wtxt
            last_fetch = time.time()
            # Full redraw
            full_img = draw_full()
            epd.init()
            epd.Clear(0xFF)
            epd.display(epd.getbuffer(full_img))
            logging.info("Full refresh (weather update) displayed.")
            # Reset partial base
            time_image = Image.new('1', (epd.height, epd.width), 255)
            time_draw = ImageDraw.Draw(time_image)
            epd.displayPartBaseImage(epd.getbuffer(time_image))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logging.error("Fatal error: %s", e)
        sys.exit(1)

    try:
        main()
    except Exception as e:
        logging.error("Fatal error: %s", e)
        sys.exit(1)
