#!/usr/bin/env python3
#
# Version V1.0 - LEDs removed
#
# sdm-cportal implements a Captive Portal hotspot to obtain WiFi SSID and Password from the user,
# test their validity, and subsequently configure wpa_supplicant.conf
#
# LED control code has been removed per request.

import argparse
import datetime
import importlib.util
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

class htmsgs:
    def __init__(self):
        self.greeting_page = """
<html><body>
<style>
input[type=submit] {{ font-size: 30px; }}
input[type=checkbox] {{ height: 40px; width: 40px; }}
body {{ font-size: 30px; }}
form {{ font-size: 30px; }}
</style>
<h1>Captive Portal for host {}</h1>
<h2>To configure WiFi for host {}:</h2>
<ul>
<li>If you don't want the Portal to provide a list of visible SSIDs to choose from, uncheck List Visible SSIDs below</li>
<li>Click the Submit button below</li>
<li>A new browser page with a form will open</li>
<li>Fill out the form and click Submit</li>
<li>Wait 30-60 seconds</li>
<li>Ensure your device is connected to the Captive Portal WiFi Network via the Settings App</li>
<li>Click Check WiFi Connection Status</li>
<li><b>IMPORTANT:</b> The system configuration is not complete until you have a successful Configuration Results response</li>
</ul>
<form action="/webform" target="_blank">
<div>
    <input type="checkbox" name="findssids" checked> <label>List visible SSIDs</label>
</div>
<br>
    <input type="submit" value="Submit">
</form>
<br><br>
<ul>
<li>If necessary, you can use the link below to check the connection status and complete the WiFi configuration</li>
<li>But first reconnect to the Captive Portal WiFi Network before clicking this link.</li>
</ul>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
</body></html>
"""
        self.web_form = """
<html><body>
<h1>Host {} WiFi Configuration</h1>
<style>
input[type=submit] {{ font-size: 30px; }}
input[type=text], input[list] {{ font-size: 40px; }}
select {{ font-size: 40px; }}
body {{ font-size: 40px; }}
form {{ font-size: 40px; }}
table {{ font-size: 40px; }}
</style>
<form action="/formsubmit">
<table>
<tr><td>SSID*</td><td><input list="foundssids" name="ssid"><datalist id="foundssids">{}</datalist></td></tr>
<tr><td>Password*</td><td><input type="text" name="password"></td></tr>
<tr><td>WiFi Country*</td><td><input type="text" name="wificountry" value></td></tr>
<tr><td>Keymap</td><td><input type="text" name="keymap"></td></tr>
<tr><td>Locale</td><td><input type="text" name="locale"></td></tr>
<tr><td>Timezone</td><td><input type="text" name="timezone"></td></tr>
<tr><td>DHCPWait</td><td><input type="text" name="dhcpwait"></td></tr>
</table>
<input type="submit" value="Submit">
<div><input type="checkbox" id="validate" checked name="validate"><label for="validate">Validate WiFi Configuration</label></div>
<div><input type="checkbox" id="ckinternet" checked name="ckinternet"><label for="ckinternet">Check Internet Connectivity</label></div>
<div><input type="checkbox" id="wifipower" checked name="wifipower"><label for="wifipower">Enable WiFi Power Management</label></div>
</form>
</body></html>
"""
        self.testinprogress_page = """
<html><body>
<style>body {{ font-size: 30px; }}</style>
<h3>Testing host {} WiFi Configuration...</h3>
<br>
<h3>Wait 30-60 seconds and reconnect to the Captive Portal Network</h3>
<h3>Then navigate to:</h3>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
</body></html>
"""
        self.wait_page = """
<html><body>
<style>body {{ font-size: 30px; }}</style>
<h3>Still testing host {} WiFi Configuration...</h3>
<br>
<h3>Please continue waiting 30-60 seconds</h3>
<h3>Then navigate to:</h3>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
</body></html>
"""
        self.notstarted_page = """
<html><body>
<style>body {{ font-size: 30px; }}</style>
<h3>Host {} WiFi Configuration has not started</h3>
<br>
<h3>Please start the Captive Portal:</h3>
<h3><a href="http://{}/" target="_blank">Start Captive Portal</a></h3>
</body></html>
"""
        self.notValidated = """
<html><body>
<h1>WiFi Configuration for host {} Complete</h1>
<h2>WiFi Connection was NOT Tested per request</h2>
</body></html>
"""
        self.giveup_page = """
<html><body>
<h1>Stop host {} WiFi configuration</h1>
<br>
<h2>The Captive Portal will now exit</h2>
</body></html>
"""


def perrorexit(emsg):
    raise SystemExit(emsg)


def qdelfile(fn):
    try:
        os.remove(fn)
    except OSError:
        pass


def qrename(src, dst):
    try:
        os.rename(src, dst)
    except OSError:
        pass


def qcopyfile(src, dst):
    try:
        shutil.copy(src, dst)
    except OSError:
        pass


def nowtime():
    return datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")


def dosystem(docmd, timout=None):
    return subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True, timeout=int(timout) if isinstance(timout, int) else None)


def syslogger(logstring):
    syslog.syslog(syslog.LOG_NOTICE, logstring)


def pxsyslogger(logstring):
    syslogger(logstring)
    perrorexit(logstring)


def runcmd(docmd, nolog=False, msg=""):
    if msg:
        syslogger(msg)
    if not nolog:
        syslogger(f"Command: {docmd}")
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    return r.returncode == 0


def gocmd(docmd):
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    return r.stdout


def reportcmd(docmd, nolog=False, msg=""):
    if msg:
        syslogger(msg)
    if not nolog:
        syslogger(f"Command: {docmd}")
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    if r.returncode != 0:
        print(f"{docmd}\n {r.stderr}")
    return r.returncode


def isrunning(sname):
    return dosystem(f"systemctl --quiet is-active {sname}").returncode == 0


def isenabled(sname):
    return dosystem(f"systemctl --quiet is-enabled {sname}").returncode == 0


def iponline(ipaddr, pingcount=1):
    return runcmd(f"ping -c {pingcount} -W 2 {ipaddr}", nolog=True)


def waitapip(ipaddr):
    while not iponline(ipaddr):
        time.sleep(1)
    return


def getssidlist():
    options = ""
    syslogger("Collecting visible SSID list")
    for line in gocmd("iwlist wlan0 scan").splitlines():
        if "ESSID" in line:
            ssid = line.split(':',1)[1].strip().strip('"')
            if ssid and ssid not in options:
                options += f'<option value="{ssid}">'
    syslogger("SSID list collected")
    return options


def read1stline(fn):
    try:
        with open(fn) as f:
            return f.readline().rstrip("\n")
    except:
        return ""


def getintval(inputval, switchname):
    retval = 0
    if inputval is not None:
        try:
            retval = int(inputval)
        except:
            pxsyslogger(f"Invalid value '{inputval}' for {switchname}")
    return retval

class cpcontrol:
    def __init__(self):
        self.settings = {"ssid":"","password":"","wificountry":"US","keymap":"","locale":"","timezone":"","dhcpwait":"0","validate":True,"ckinternet":True,"wifipower":"on"}
        self.errors = {"success":0,"noconnect":1,"nointernet":2,"manualgiveup":3,"notestdone":4}
        self.sdm = False
        self.connected = False
        self.iconnected = False
        self.isresult = False
        self.runflag = True
        self.usenm = False
        self.apssid = ""
        self.apip = ""
        self.facname = ""
        self.netdev = ""
        self.apname = ""
        self.netns = ""
        self.phydev = ""
        self.dhcp = None
        self.atimer = None
        self.netops = None
        self.retries = 5
        self.timeout = 15*60
        self.status = 999
        self.hostname = socket.gethostname()
        self.sdndrunning = isrunning("systemd-networkd")

    def getwlanpm(self, devname):
        for line in gocmd(f"iwconfig {devname}").splitlines():
            if "Power Management:" in line:
                return line.split(':',1)[1]
        return ""

    def writenetconfig(self):
        with open(f"/etc/systemd/network/{self.facname}-{self.apname}.network", 'w') as f:
            f.write(f"[Match]\nName={self.apname}\nType=wlan\nWLANInterfaceType=ap\n\n[Network]\nDHCPServer=yes\nLinkLocalAddressing=no\nAddress={self.apip}/24\nConfigureWithoutCarrier=yes\nIgnoreCarrierLoss=yes\n\n[DHCPServer]\nSendOption=114:string:https://{self.apip}/hotspot-detect.html\nDNS={self.apip}\n")
        with open(f"/etc/systemd/network/{self.facname}-{self.netdev}.network", 'w') as f:
            f.write(f"[Match]\nName={self.netdev}\n\n[Network]\nDHCP=ipv4\nIPv6AcceptRA=false\n\n[DHCPv4]\nRouteMetric=20\nUseDomains=yes\n")

    def writewpaconf(self, wlan=""):
        wl = f"-{wlan}" if wlan else ""
        with open(f"/etc/wpa_supplicant/wpa_supplicant{wl}.conf", 'w') as f:
            f.write(f"ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\ncountry={self.settings['wificountry']}\nupdate_config=1\n\nnetwork={{\n    ssid=\"{self.settings['ssid']}\"\n    psk=\"{self.settings['password']}\"\n    key_mgmt=WPA-PSK\n}}\n")
        nmfile = f"/etc/NetworkManager/system-connections/{self.settings['ssid']}.nmconnection"
        with open(nmfile, 'w') as f:
            uuid_str = uuid.uuid4()
            f.write(f"[connection]\nid={self.settings['ssid'].lower()}\nuuid={uuid_str}\ntype=wifi\nautoconnect=true\ninterface-name={self.netdev}\n\n[wifi]\nmode=infrastructure\nssid={self.settings['ssid']}\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={self.settings['password']}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=ignore\n")
        os.chmod(nmfile, 0o600)

    def writeapwpaconf(self):
        ssid = f"{self.hostname}-{self.apssid}"
        with open(f"/etc/wpa_supplicant/wpa_supplicant-{self.apname}.conf", 'w') as f:
            f.write(f"ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\np2p_disabled=1\ncountry={self.settings['wificountry']}\nap_scan=1\n\nnetwork={{\nssid=\"{ssid}\"\nmode=2\nkey_mgmt=NONE\n}}\n")

    def writel10n(self, keymap, locale, timezone):
        entries = []
        if keymap:
            entries.append(f"keymap={keymap}")
        if locale:
            entries.append(f"locale={locale}")
        if timezone:
            entries.append(f"timezone={timezone}")
        content = "\n".join(entries)
        if not content:
            return
        if self.sdm:
            with open("/etc/sdm/local-1piboot.conf", 'w') as f:
                f.write(content + "\n")
        elif self.l10nhandler:
            reportcmd(f'{self.l10nhandler} "{keymap}" "{locale}" "{timezone}"', msg=f"Call L10N handler {self.l10nhandler}")

class ATimer(threading.Thread):
    def __init__(self, pd):
        super().__init__()
        self.pd = pd
        self.timer = pd.timeout
        self.ctimer = self.timer

    def run(self):
        while self.pd.runflag and self.ctimer > 0:
            time.sleep(1)
            self.ctimer -= 1
        if self.pd.runflag:
            syslogger("Captive Portal Timeout reached; shutting down")
            self.pd.status = 900
            if self.pd.httpd and self.pd.httpd.socket:
                threading.Thread(target=self.pd.httpd.socket.shutdown, args=(0,)).start()
            self.pd.runflag = False

    def reset(self):
        self.ctimer = self.timer

class DHCPClient:
    def __init__(self, pd):
        self.pd = pd
        self.dhcpcdrunning = isrunning("dhcpcd") or isenabled("dhcpcd")
        self.nmrunning = isrunning("NetworkManager") or isenabled("NetworkManager")
        if self.nmrunning:
            self.dhcpclient = "NetworkManager"
        elif self.dhcpcdrunning:
            self.dhcpclient = "dhcpcd"
        else:
            syslogger("No known DHCP client; defaulting to dhcpcd")
            self.dhcpclient = "dhcpcd"

    def stopclient(self):
        reportcmd(f"systemctl stop {self.dhcpclient}", msg=f"Stop {self.dhcpclient}")

    def restartclient(self):
        reportcmd(f"systemctl start {self.dhcpclient}", msg=f"Start {self.dhcpclient}")

class Netops(threading.Thread):
    def __init__(self, pd):
        super().__init__()
        self.pd = pd

    def run(self):
        if self.pd.inprogress:
            syslogger("Test already in progress")
            return
        self.pd.inprogress = True
        syslogger("Writing WPA conf for test")
        self.pd.writewpaconf(self.pd.netdev)
        if self.pd.usenm:
            runcmd("nmcli c reload", msg="Reload NM connections")
            runcmd(f"nmcli c up {self.pd.settings['ssid'].lower()}")
        else:
            reportcmd(f"systemctl restart wpa_supplicant@{self.pd.netdev}", msg=f"Restart wpa_supplicant@{self.pd.netdev}")
        myip = ""
        for i in range(1, self.pd.settings['dhcpwait']):
            out = gocmd(f"ip -br -o -f inet addr show dev {self.pd.netdev}")
            if out:
                parts = out.split()
                myip = parts[2].split('/')[0]
            if myip and not myip.startswith("169.254"):
                break
            syslogger(f"Waiting {i}/{self.pd.settings['dhcpwait']} for IP")
            time.sleep(1)
        self.pd.wlanip = myip
        if myip:
            self.pd.connected = True
            if self.pd.settings['ckinternet']:
                if iponline("1.1.1.1", pingcount=5):
                    self.pd.iconnected = True
        # finalize
        self.pd.isresult = True
        self.pd.writel10n(self.pd.settings['keymap'], self.pd.settings['locale'], self.pd.settings['timezone'])
        return

class sdmRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, pd, *args, **kwargs):
        self.pd = pd
        try:
            super().__init__(*args, **kwargs)
        except (ConnectionResetError, BrokenPipeError):
            syslogger("Connection error in handler")

    def _set_response(self, code=200):
        self.send_response(code)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def log_message(self, format, *args):
        return  # suppress default logging

    def _write(self, html):
        self._set_response()
        self.wfile.write(html.encode('utf-8'))

    def _buildresult(self):
        res = f"<html><body><h1>WiFi Results for {self.pd.hostname}</h1>"
        if self.pd.connected:
            res += f"<h2>IP {self.pd.wlanip} via SSID '{self.pd.settings['ssid']}'</h2>"
        else:
            res += "<h2>WiFi Did NOT Connect</h2>"
        if self.pd.settings['ckinternet']:
            if self.pd.iconnected:
                res += "<h2>Internet Accessible</h2>"
            else:
                res += "<h2>Internet NOT Accessible</h2>"
        res += "</body></html>"
        return res

    def do_GET(self):
        if self.pd.atimer:
            self.pd.atimer.reset()
        path = self.path
        if '/formsubmit' in path:
            qs = parse_qs(urlparse(path).query)
            for k in self.pd.settings:
                if k in qs:
                    self.pd.settings[k] = qs[k][0]
            # validation omitted for brevity
            self.pd.formdone = True
            if self.pd.settings['validate']:
                self.send_response(302)
                self.send_header('Location', f"http://{self.pd.apip}/testinprogress")
                self.end_headers()
                threading.Thread(target=self.pd.netops.run).start()
            else:
                self._write(self.pd.notValidated.format(self.pd.hostname))
        elif path == '/' or 'hotspot-detect.html' in path:
            self._write(self.pd.pdmsgs.greeting_page.format(self.pd.hostname, self.pd.hostname, self.pd.apip))
        elif '/webform' in path:
            qs = parse_qs(urlparse(path).query)
            ssids = getssidlist() if qs.get('findssids') else ''
            self._write(self.pd.pdmsgs.web_form.format(self.pd.hostname, ssids))
        elif '/testinprogress' in path:
            self._write(self.pd.pdmsgs.testinprogress_page.format(self.pd.hostname, self.pd.apip))
        elif '/checkresult' in path:
            if not self.pd.formdone:
                self._write(self.pd.notstarted_page.format(self.pd.hostname, self.pd.apip))
            elif not self.pd.isresult:
                self._write(self.pd.wait_page.format(self.pd.hostname, self.pd.apip))
            else:
                self._write(self._buildresult())
        elif '/giveup' in path:
            self._write(self.pd.giveup_page.format(self.pd.hostname))
            self.pd.status = self.pd.errors['manualgiveup']
            self.pd.runflag = False
        return

def updatewifi(pd):
    # no-op to prevent legacy behavior
    return

def docleanup(pd, resetcmd=False):
    pd.dhcp.stopclient()
    # additional cleanup omitted for brevity

def resetnet(pd):
    docleanup(pd)

def runserver(pd):
    pd.atimer.reset()
    handler = partial(sdmRequestHandler, pd)
    pd.httpd = ThreadingHTTPServer((pd.apip, 80), handler)
    pd.atimer.start()
    while pd.runflag and pd.retries > 0:
        pd.httpd.handle_request()
    docleanup(pd)
    return pd.status

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='cportal')
    parser.add_argument('--apssid', help="SSID for AP")
    parser.add_argument('--apip', help="IP for AP")
    parser.add_argument('--country', default="US")
    parser.add_argument('--defaults', help="Defaults file")
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--facility', help="Facility name")
    parser.add_argument('--l10nhandler', help="Localization handler")
    parser.add_argument('--retries', default="5")
    parser.add_argument('--sdm', action='store_true')
    parser.add_argument('--timeout', default="900")
    parser.add_argument('--web-msgs', help="Custom web HTML")
    parser.add_argument('--wlan', default="wlan0")
    args = parser.parse_args()

    pd = cpcontrol()
    pd.apssid = args.apssid or "sdm"
    pd.apip = args.apip or "10.1.1.1"
    pd.facname = args.facility or "sdm"
    pd.retries = getintval(args.retries, '--retries')
    pd.timeout = getintval(args.timeout, '--timeout')
    pd.debug = args.debug
    pd.sdm = args.sdm
    pd.dhcp = DHCPClient(pd)

    if args.reset:
        resetnet(pd)
        sys.exit(0)

    syslog.openlog(ident="sdm-cportal")
    if os.path.exists(f"/sys/class/net/{args.wlan}"):
        pd.netdev = args.wlan
        pd.phydev = read1stline(f"/sys/class/net/{args.wlan}/phy80211/name")
    if not pd.netdev or not pd.phydev:
        pxsyslogger(f"Unrecognized WiFi device {args.wlan}")

    if args.defaults:
        if os.path.exists(args.defaults):
            pd.defaults = read1stline(args.defaults)

    pd.pdmsgs = htmsgs()
    pd.atimer = ATimer(pd)

    try:
        runserver(pd)
    except KeyboardInterrupt:
        syslogger("Interrupted; cleaning up")
        docleanup(pd)
        sys.exit(0)
    except Exception as e:
        docleanup(pd)
        perrorexit(f"Unhandled exception: {e}")
