#!/usr/bin/env python3
#
# Version V1.1 - Minimal Captive Portal (LEDs and extra visual elements removed)
#
# Starts a Captive Portal hotspot on Raspberry Pi, obtains WiFi SSID and password,
# configures wpa_supplicant.conf and NetworkManager, tests connectivity, then exits.

import argparse
import datetime
import os
import shutil
import socket
import subprocess
import syslog
import threading
import time
import uuid
from functools import partial
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Minimal HTML pages (kept for basic user input and results only)
class htmsgs:
    def __init__(self):
        self.greeting_page = """
<html><body>
<h1>Captive Portal for {}</h1>
<form action="/webform" target="_blank">
    <input type="submit" value="Configure WiFi">
</form>
</body></html>
"""
        self.web_form = """
<html><body>
<h1>Configure WiFi for {}</h1>
<form action="/formsubmit">
SSID*: <input type="text" name="ssid"><br>
Password*: <input type="text" name="password"><br>
WiFi Country*: <input type="text" name="wificountry" value="US"><br>
<input type="submit" value="Submit">
</form>
</body></html>
"""
        self.result_page = """
<html><body>
<h1>Configuration Complete for {}</h1>
<p>WiFi SSID: {} | Status: {}</p>
</body></html>
"""

# Utility functions
def syslogger(msg):
    syslog.syslog(syslog.LOG_NOTICE, msg)

def run_command(cmd, timeout=None):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True, timeout=timeout)

# Main controller class
class cpcontrol:
    def __init__(self):
        self.settings = {"ssid": "", "password": "", "wificountry": "US"}
        self.hostname = socket.gethostname()
        self.apip = ""
        self.netdev = "wlan0"
        self.httpd = None
        self.runflag = True
        self.result = "Pending"

    def write_configs(self):
        # Write wpa_supplicant.conf
        with open(f"/etc/wpa_supplicant/wpa_supplicant-{self.netdev}.conf", 'w') as f:
            f.write(f"ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
                    f"country={self.settings['wificountry']}\nupdate_config=1\n\n"
                    f"network={{\n    ssid=\"{self.settings['ssid']}\"\n    psk=\"{self.settings['password']}\"\n}}\n")
        # Write NetworkManager config
        nmfile = f"/etc/NetworkManager/system-connections/{self.settings['ssid']}.nmconnection"
        uuid_str = uuid.uuid4()
        with open(nmfile, 'w') as f:
            f.write(f"[connection]\nid={self.settings['ssid'].lower()}\nuuid={uuid_str}\ntype=wifi\nautoconnect=true\n"
                    f"interface-name={self.netdev}\n\n[wifi]\nmode=infrastructure\nssid={self.settings['ssid']}\n\n"
                    f"[wifi-security]\nkey-mgmt=wpa-psk\npsk={self.settings['password']}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=ignore\n")
        os.chmod(nmfile, 0o600)

    def test_connection(self):
        # Simple ping test for connectivity
        result = run_command("ping -c 3 -W 2 1.1.1.1")
        self.result = "Connected" if result.returncode == 0 else "Failed"

# HTTP handler
class PortalHandler(BaseHTTPRequestHandler):
    def __init__(self, pd, *args, **kwargs):
        self.pd = pd
        try:
            super().__init__(*args, **kwargs)
        except (ConnectionResetError, BrokenPipeError):
            syslogger("Connection error in handler")

    def log_message(self, format, *args):  # Suppress logs
        return

    def _send_html(self, html):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_GET(self):
        path = self.path
        if '/webform' in path:
            self._send_html(self.pd.pdmsgs.web_form.format(self.pd.hostname))
        elif '/formsubmit' in path:
            qs = parse_qs(urlparse(path).query)
            self.pd.settings.update({k: qs[k][0] for k in ["ssid", "password", "wificountry"] if k in qs})
            self.pd.write_configs()
            self.pd.test_connection()
            self._send_html(self.pd.pdmsgs.result_page.format(self.pd.hostname, self.pd.settings["ssid"], self.pd.result))
            self.pd.runflag = False  # Exit after setup
        else:
            self._send_html(self.pd.pdmsgs.greeting_page.format(self.pd.hostname))

def runserver(pd):
    handler = partial(PortalHandler, pd)
    pd.httpd = ThreadingHTTPServer((pd.apip, 80), handler)
    while pd.runflag:
        pd.httpd.handle_request()
    pd.httpd.server_close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apip', default="10.1.1.1")
    args = parser.parse_args()

    syslog.openlog(ident="sdm-cportal")
    pd = cpcontrol()
    pd.apip = args.apip
    pd.pdmsgs = htmsgs()

    try:
        runserver(pd)
    except KeyboardInterrupt:
        syslogger("Interrupted; shutting down")
    finally:
        syslogger("Captive Portal exiting")
