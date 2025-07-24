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
FONT_PATH = os.path.join(BASE_DIR, 'lib', 'font', 'aktiv.otv')

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
        loc = j.get("location", "Unknown")
        # Extract timezone
        tz_str = j.get("timezone") or "America/Vancouver"
        # Extract weather
        w = j["weather"]["data"]["weather"]
        desc = w.get("description", "n/a").capitalize()
        temp = w.get("temp", {}).get("cur")
        weather_text = f"{desc}, {temp:.1f}°C"
        return loc, weather_text, tz_str
    except Exception as e:
        logging.error("Data fetch failed: %s", e)
        return None, "Weather unavailable", None


def main():
    # Initialize display
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)

    # Load fonts
    try:
        font_loc = ImageFont.truetype(FONT_PATH, 18)
        font_time = ImageFont.truetype(FONT_PATH, 48)
        font_wthr = ImageFont.truetype(FONT_PATH, 16)
    except Exception:
        font_loc = font_time = font_wthr = ImageFont.load_default()

    last_fetch = 0
    location = "Vancouver"
    weather_text = ""
    timezone_str = "America/Vancouver"

    while True:
        now_ts = time.time()
        if now_ts - last_fetch >= FETCH_INTERVAL:
            loc, wtxt, tz_new = fetch_data()
            if loc:
                location = loc
            if tz_new:
                timezone_str = tz_new
            weather_text = wtxt
            last_fetch = now_ts

        # Compute current time
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("America/Vancouver")
        now = datetime.now(tz).strftime("%H:%M")

        # Create canvas (height x width)
        img = Image.new('1', (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(img)

        # Draw location at top
        w, h = draw.textsize(location, font=font_loc)
        x = (epd.height - w) // 2
        draw.text((x, 5), location, font=font_loc, fill=0)

        # Draw large time in center
        w, h = draw.textsize(now, font=font_time)
        x = (epd.height - w) // 2
        y = (epd.width - h) // 2 - 10
        draw.text((x, y), now, font=font_time, fill=0)

        # Draw weather at bottom
        w, h = draw.textsize(weather_text, font=font_wthr)
        x = (epd.height - w) // 2
        draw.text((x, epd.width - h - 5), weather_text, font=font_wthr, fill=0)

        # Display
        epd.display(epd.getbuffer(img))
        logging.info("Displayed %s | %s | TZ=%s", now, weather_text, timezone_str)
        epd.sleep()

        # Sleep to next minute boundary
        now_ts = time.time()
        sleep_secs = UPDATE_INTERVAL - (now_ts % UPDATE_INTERVAL)
        time.sleep(sleep_secs)
        epd.init()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logging.error("Fatal error: %s", e)
        sys.exit(1)
