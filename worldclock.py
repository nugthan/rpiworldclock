#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os

libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd2in13_V4
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image,ImageDraw,ImageFont
import traceback

from dotenv import load_dotenv
load_dotenv()
WEATHER_URL = os.getenv("WEATHER_URL", "https://webfoundry.io/api/weather")
API_KEY     = os.getenv("API_KEY", "")  # your API key loaded from .env
FETCH_INTERVAL = 30 * 60  # seconds between weather fetches
UPDATE_INTERVAL = 60      # seconds between display updates

logging.basicConfig(level=logging.DEBUG)

# Fetch weather and timezone once every FETCH_INTERVAL
def fetch_weather_and_timezone():
    try:
        params = {}
        if API_KEY:
            params['key'] = API_KEY  # API expects ?key={key}
        r = requests.get(WEATHER_URL, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        # Extract timezone field if provided
        tz_str = j.get("timezone", None)
        # Fallback: use default Vancouver if missing
        if not tz_str:
            tz_str = "America/Vancouver"
        # Extract weather info
        w = j["weather"]["data"]["weather"]
        desc = w.get("description", "n/a").capitalize()
        temp = w.get("temp", {}).get("cur")
        if temp is None:
            temp = j["weather"]["data"]["weather"]["temp"]["cur"]
        weather_text = f"{desc}, {temp:.1f}°C"
        return weather_text, tz_str
    except Exception as e:
        logging.error("Weather fetch failed: %s", e)
        # return placeholders and keep existing timezone
        return "Weather unavailable", None

def main():
    # Initialize e-ink display
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)

    font = ImageFont.load_default()
    last_fetch = 0
    weather_text = ""
    timezone_str = "America/Vancouver"

    while True:
        now_ts = time.time()
        # Fetch new weather and timezone if needed
        if now_ts - last_fetch >= FETCH_INTERVAL:
            wt, tz_new = fetch_weather_and_timezone()
            if tz_new:
                timezone_str = tz_new
            weather_text = wt
            last_fetch = now_ts

        # Get current time in the dynamic timezone
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("America/Vancouver")
        now = datetime.now(tz).strftime("%H:%M")

        # Create image canvas (height x width)
        img = Image.new('1', (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(img)

        # Draw time and weather
        lines = [f"Time: {now}", f"Weather: {weather_text}"]
        y = 10
        for line in lines:
            w, h = draw.textsize(line, font=font)
            x = (epd.height - w) // 2
            draw.text((x, y), line, font=font, fill=0)
            y += h + 5

        # Display and sleep
        epd.display(epd.getbuffer(img))
        logging.info("Updated display: %s | %s | TZ=%s", now, weather_text, timezone_str)
        epd.sleep()

        # Wait until next update
        time.sleep(UPDATE_INTERVAL)
        epd.init()

# Entry point
if __name__ == "__main__":
    main()
