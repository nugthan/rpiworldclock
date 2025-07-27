#!/usr/bin/env python3
#
# Version V1.0
#
# sdm-cportal implements a Captive Portal hotspot to obtain WiFi SSD and Password from the user,
# test their validity, and subsequently configure wpa_supplicant.conf
#
# sdm-cportal is part of sdm, a tool that enables you to prepare IMGs that are fully customized
# By using sdm-cportal with an sdm-prepared IMG, the WiFi SSID and password are not bound until
# the system first boots.
#
# sdm-cportal can be used standalone, independently of sdm as well. sdm-cportal is documented
# as part of sdm: https://github.com/gitbls/sdm/blob/master/Docs/Captive-Portal.md
#
#
# TODO
#  Remove wpa_supplicant.conf in cleanup if using networkmanager
#  Review using networkmanager for access point
#

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
from functools    import partial
from http.server  import ThreadingHTTPServer
from http.server  import BaseHTTPRequestHandler
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
<li>Wait until the ACT LED flashes "...." or "---." or 30-60 seconds</li>
<li>Ensure your device is connected to the Captive Portal WiFi Network via the Settings App</li>
<li>Click Check WiFi Connection Status</li>
<li><b>IMPORTANT:</b> The system configuration is not complete until you have a successful Configuration Results response</li>
</ul>
<form action="/webform" target="_blank">
<div>
    <input type="checkbox" name="findssids" checked="checked">
    <label for="findssids">List visible SSIDs (takes a bit of time to collect)</label>
</div>
<br>
    <input type="submit" value="Submit">
</form>
</font>
<br><br>
<ul>
<li>If necessary, you can use the link below to check the connection status and complete the WiFi configuration</li>
<li>But first use the Settings App on your device to ensure you're connected to the Captive Portal WiFi Network again before clicking this link. <b>Turn WiFi Off/On, reconnect to the Captive Portal WiFi Network</b>
</ul>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
  </body></html>
"""

        self.web_form = """
 <html><body>
  <h1>Host {} WiFi Configuration</h1>
<br>
<style>
input[type=submit] {{ font-size: 30px; }}
input[type=text] {{ font-size: 40px; }}
input[list] {{ font-size: 40px; }}
input[type=checkbox] {{ height: 40px; width: 40px; }}
select {{ font-size: 40px; }}
h1 {{ font-size: 50px; }}
body {{ font-size: 40px; }}
form {{ font-size: 40px; }}
table {{ font-size: 40px; }}
</style>
<form action="/formsubmit">
    <table>
<tr><td>SSID*</td><td><input type="list" list="foundssids" name="ssid"></label>
<datalist id="foundssids">
{}
</datalist></td></tr>
      <tr><td>Password*</td><td><input type="text" name="password" value=""></td></tr>
      <tr><td><b>WiFi Country*</b></td><td><input type="text" name="wificountry" value=""></td></tr>
      <tr><td>Keymap</td><td><input type="text" name="keymap" value=""></td></tr>
      <tr><td>Locale</td><td><input type="text" name="locale" value=""></td></tr>
      <tr><td>Timezone</td><td><input type="text" name="timezone" value=""></td></tr>
      <tr><td>DHCPWait</td><td><input type="text" name="dhcpwait" value=""></td></tr>
    </table><p>
    <input type="submit" value="Submit">
  <div>
     <input type="checkbox" id="validate" checked name="validate">
    <label for="validate">Validate WiFi Configuration by Connecting</label>
  </div>
  <div>
     <input type="checkbox" id="ckinternet" checked name="ckinternet">
    <label for="ckinternet">Check Internet Connectivity after WiFi Connected</label>
  </div>
  <div>
     <input type="checkbox" id="wifipower" checked name="wifipower">
    <label for="wifipower">Enable WiFi Power Management</label>
  </div>
  </form>
*  Entry is Required
  </body></html>
"""
        self.testinprogress_page = """
<html><body>
<style>
body {{ font-size: 30px; }}
</style>
<h3>Testing host {} WiFi Configuration...</h3>
<br>
<h3>Wait until the ACT LED flashes "...." or "---." or 30-60 seconds</h3>
<h3>Use the Settings app on your device to turn WiFi off/on...</h3>
<h3>...and then reconnect to the Captive Portal WiFi Network</h3>
<h3>Once connected, navigate to:</h3>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
</body></html>
"""

        self.wait_page = """
<html><body>
<style>
body {{ font-size: 30px; }}
</style>
<h3>Still testing host {} WiFi Configuration...</h3>
<br>
<h3>Please continue waiting until the ACT LED flashes "...." or "---." or 30-60 seconds</h3>
<h3>Use the Settings app on your device to turn WiFi off/on...</h3>
<h3>...and then reconnect to the Captive Portal WiFi Network</h3>
<h3>Once connected, navigate to:</h3>
<h3><a href="http://{}/checkresult" target="_blank">Check WiFi connection status</a></h3>
</body></html>
"""
        self.notstarted_page = """
<html><body>
<style>
body {{ font-size: 30px; }}
</style>
<h3>Host {} WiFi Configuration has not started</h3>
<br>
<h3>You MUST step through the Captive Portal in order</h3>
<h3>Please click this link to start the Captive Portal</h3>
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
<h2>Consult your system provider for assistance</h2>
</body></html>
"""

def perrorexit(emsg):
    """
    Print the message and exit the program
    """
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
    """
    Copy src file to dst
    """
    try:
        shutil.copy(src, dst)
    except OSError:
        pass
    return

def nowtime():
    return datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")  

def dosystem(docmd, timout=None):
    """
    Returns the result from subprocess.run, which contains stdout, returncode, etc.
    """
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True, timeout=int(timout) if type(timout) is int else None)
    return r

def syslogger(logstring):
    syslog.syslog(syslog.LOG_NOTICE, logstring)


def pxsyslogger(logstring):
    # syslog and then exit
    syslogger(logstring)
    perrorexit(logstring)

def runcmd(docmd, nolog=False, msg=""):
    #
    # Returns return status from the command
    #
    if msg != "": syslogger(msg)
    if nolog is False: syslogger(f"Command: {docmd}")
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    return r.returncode == 0
    
def gocmd(docmd):
    #
    # Returns stdout from the command
    #
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    return r.stdout
    
def reportcmd(docmd, nolog=False, msg=""):
    #
    # syslog it unless nolog=True
    # If error status return print stderr
    #
    if msg != "": syslogger(msg)
    if nolog is False: syslogger(f"Command: {docmd}")
    r = subprocess.run(docmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    if r.returncode != 0:
        print(f"{docmd}\n {r.stderr}")
    return r.returncode

def isrunning(sname):
    r = dosystem(f"systemctl --quiet is-active {sname}")
    return r.returncode == 0
    
def isenabled(sname):
    r = dosystem(f"systemctl --quiet is-enabled {sname}")
    return r.returncode == 0

def iponline(ipaddr, pingcount=1):
    return runcmd(f"ping -c {pingcount} -W 2 {ipaddr}", nolog=True)

def waitapip(ipaddr):
    nomsg = True
    while not iponline(ipaddr):
        if nomsg:
            syslogger("Wait for Access Point IP to come online")
            nomsg = False
        time.sleep(1)
    return

def getssidlist():
    ssidlist = ""
    syslogger("Collecting visible SSID list")
    for line in gocmd("iwlist wlan0 scan").split('\n'):
        if "ESSID" in line:
            essid, ssid = line.split(":")
            ssid = ssid[1:-1] # Strip leading/trailing quotes
            if ssid != "" and not ssid in ssidlist:
                ssidlist = f'{ssidlist}<option value="{ssid}">'
    syslogger("SSID list collected")
    return ssidlist

def read1stline(fn):
    try:
        with open(fn) as f: return f.readline().strip('\n')
    except:
        return ""

def getintval(inputval, switchname):
    retval = 0
    if not inputval is None:
        try:
            retval = int(inputval)
        except:
            pxsyslogger(f"? Invalid value '{inputval}' for {switchname}")
    return retval

class cpcontrol:
    def __init__(self):
        self.ledseq = { "APoff":"----", "APon":"-.--", "Testing":"--.-", "ResultGood":"....", "ResultBad":"---.", "Cleanup":"...-" }
        self.settings = { "ssid":"", "password":"", "wificountry":"US", "keymap":"", "locale":"", "timezone":"",\
                          "dhcpwait":"0", "validate":True, "ckinternet":True, "wifipower":"on" }
        self.errors = { "success":0, "noconnect":1, "nointernet":2, "manualgiveup":3, "notestdone":4 }
        self.sdm = self.connected = self.iconnected = self.isresult = False
        self.runflag = True
        self.usenm = False
        self.uapname = "uap0"
        self.formdone = self.inprogress = self.debug = False
        self.l10nhandler = self.defaults = self.allerrors = self.wlanip = self.apip = ""
        self.apssid = self.logmsg = self.facname = self.netns = self.apname = self.netdev = self.apdev = self.phydev = ""
        self.httpd = self.args = self.pdmsgs = None
        self.leds = self.netops = self.dhcp = self.atimer = None
        self.retries = 5
        self.timeout = 15*60
        self.status = 999
        self.hostname = socket.gethostname()
        self.sdndrunning = True if isrunning("systemd-networkd") == 0 else False

    def getwlanpm(self, devname):
        op = gocmd(f"iwconfig {devname}")
        for line in op.split('\n'):
            if "Power Management:" in line: return line.split(':')[1]
        return ""

    def writenetconfig(self):
        with open(f"/etc/systemd/network/{self.facname}-{self.apname}.network", 'w') as f:
            f.write(f"[Match]\n\
Name={self.apname}\n\
Type=wlan\n\
WLANInterfaceType=ap\n\
\n\
[Network]\n\
DHCPServer=yes\n\
LinkLocalAddressing=no\n\
Address={self.apip}/24\n\
ConfigureWithoutCarrier=yes\n\
IgnoreCarrierLoss=yes\n\
\n\
[DHCPServer]\n\
SendOption=114:string:https://{self.apip}/hotspot-detect.html\n\
DNS={self.apip}\n")

        with open(f"/etc/systemd/network/{self.facname}-{self.netdev}.network", 'w') as f:
            f.write(f"[Match]\n\
Name={self.netdev}\n\
\n\
[Network]\n\
DHCP=ipv4\n\
IPv6AcceptRA=false\n\
\n\
[DHCPv4]\n\
RouteMetric=20\n\
UseDomains=yes\n")

    def writewpaconf(self, wlan=""):
        wl = "" if wlan == "" else f"-{wlan}"
        lcssid=self.settings['ssid'].lower()
        with open(f"/etc/wpa_supplicant/wpa_supplicant{wl}.conf", 'w') as f:
            f.write(f"ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n\
country={self.settings['wificountry']}\n\
update_config=1\n\
\n\
network={{\n\
    ssid=\"{self.settings['ssid']}\"\n\
    psk=\"{self.settings['password']}\"\n\
    key_mgmt=WPA-PSK\n}}\n")
        with open(f"/etc/NetworkManager/system-connections/{self.settings['ssid']}.nmconnection", 'w') as f:
            f.write(f"[connection]\n\
id={lcssid}\n\
uuid={uuid.uuid4()}\n\
type=wifi\n\
autoconnect=true\n\
interface-name=wlan0\n\
\n\
[wifi]\n\
mode=infrastructure\n\
ssid={self.settings['ssid']}\n\
\n\
[wifi-security]\n\
key-mgmt=wpa-psk\n\
psk={self.settings['password']}\n\
\n\
[ipv4]\n\
method=auto\n\
\n\
[ipv6]\n\
method=ignore\n")
        os.chmod(f"/etc/NetworkManager/system-connections/{self.settings['ssid']}.nmconnection",0o600)

    def writeapwpaconf(self):
        ssid = f"{self.hostname}-{self.apssid}"
        with open(f"/etc/wpa_supplicant/wpa_supplicant-{self.apname}.conf", 'w') as f:
            f.write(f"ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n\
p2p_disabled=1\n\
country={self.settings['wificountry']}\n\
ap_scan=1\n\
\n\
network={{\n\
ssid=\"{ssid}\"\n\
mode=2\n\
key_mgmt=NONE\n}}\n")

    def writel10n(self, keymap, locale, timezone):
        ostr = ""
        if keymap != "": ostr = f"keymap={keymap}"
        if locale != "": ostr = f"{ostr}\nlocale={locale}"
        if timezone != "": ostr = f"{ostr}\ntimezone={timezone}"
        if ostr != "":
            if self.sdm:
                with open(f"/etc/sdm/local-1piboot.conf", 'w') as f:
                    f.write(f"{ostr}\n")
            else:
                if self.l10nhandler != "":
                    reportcmd(f'{self.l10nhandler} "{keymap}" "{locale}" "{timezone}"', msg=f"Call L10N handler {self.l10nhandler}")

class ATimer(threading.Thread):
    def __init__(self, pd):
        threading.Thread.__init__(self)
        self.pd = pd
        self.timer = self.pd.timeout
        self.ctimer = self.timer

    def __del__(self):
        if self.pd.debug: syslogger("ATimer object deleted")

    def run(self):
        #
        # Count down the timer to 0. if hits 0: stop everything: leds, netops, webservice
        #
        while True and self.pd.runflag:
            time.sleep(1)
            self.ctimer -= 1
            if self.ctimer <= 0:
                syslogger("Captive Portal Timeout reached; shutting down")
                self.pd.status = 900
                if self.pd.debug: syslogger("Shutting down threads")
                if not self.pd.httpd is None:
                    if not self.pd.httpd.socket is None: threading.Thread(target=self.pd.httpd.socket.shutdown(0)).start()
                    #threading.Thread(target=self.pd.httpd.shutdown()).start()
                self.pd.runflag = False
                if self.pd.debug: syslogger("Done Shutting down threads")
        return

    def reset(self):
        if self.pd.debug: syslogger("ATimer reset")
        self.ctimer = self.timer

class DHCPClient():
    def __init__(self, pd):
        self.pd = pd
        self.dhcpclient = ""
        self.dhcpcdrunning = False
        self.nmrunning = False
        if isrunning("dhcpcd") or isenabled("dhcpcd"):
            self.dhcpcdrunning = True
            self.dhcpclient = "dhcpcd"
        if isrunning("NetworkManager") or isenabled("NetworkManager"):
            self.nmrunning = True
            self.dhcpclient = "NetworkManager"
        if self.dhcpclient == "":
            syslogger("No known running/enabled DHCP client found; assuming dhcpcd")
            self.dhcpclient = "dhcpcd"
        return

    def stopclient(self):
        reportcmd(f"systemctl stop {self.dhcpclient}", msg=f"Stop {self.dhcpclient}")

    def restartclient(self):
        if self.dhcpcdrunning or self.nmrunning:
            reportcmd(f"systemctl start {self.dhcpclient}", msg=f"Start {self.dhcpclient}")

class LEDflash(threading.Thread):
    def __init__(self, pd):
        threading.Thread.__init__(self)
        self.dit = 0.2
        self.dot = 0.5
        self.interval = 0.3
        self.xinterval = 0.5
        self.pd = pd
        self.sequence = ""
        self.running = True
        self.actled = open("/sys/class/leds/ACT/brightness", 'w')

    def __del__(self):
        if self.pd.debug: syslogger("LEDflash object deleted")

    def writeflush(self, ch):
        if not self.running: return
        self.actled.write(ch)
        self.actled.flush()

    def flashled(self, ch, ontime):
        if not self.running: return
        self.writeflush("1")
        time.sleep(ontime)
        self.writeflush("0")

    def setsequence(self, newsequence):
        self.sequence = newsequence
        syslogger(f'Set LED flash sequence: "{newsequence}"')
        return

    def setstopled(self):
        self.sequence = ""
        self.writeflush("0")
        self.running = False

    def run(self):
        while self.running:
            flashthis = self.sequence
            if flashthis != "":
                for i in range(0, len(flashthis)):
                    ch = flashthis[i]
                    ontime = self.dit if ch == "." else self.dot
                    if self.running:
                        self.flashled(ch, ontime)
                    else:
                        break
                    if self.running: time.sleep(self.interval)
            if self.running: time.sleep(self.xinterval)
        return

class Netops(threading.Thread):
    def __init__(self, pd):
        threading.Thread.__init__(self)
        self.pd = pd

    def __del__(self):
        if self.pd.debug: syslogger("Netops object deleted")

    def run(self):
        if self.pd.inprogress:
            syslogger(f"Test Inputs already in progress")
            return
        self.pd.isresult = False
        self.pd.inprogress = True
        syslogger(f"Write wpa_supplicant-{self.pd.netdev}.conf")
        self.pd.leds.setsequence(self.pd.ledseq['Testing'])
        self.pd.writewpaconf(f"{self.pd.netdev}")
        if self.pd.usenm:
            runcmd("nmcli c reload", "Reload NetworkManager connections")
            runcmd(f"nmcli c up {self.pd.settings['ssid'].lower()}")
        else:
            # try this again someday
            #if "OK" in gocmd(f"wpa_cli -i {self.pd.netdev} reconfigure"):
            #syslogger(f"Successfully reconfigured {self.pd.netdev} wpa_supplicant")
            #else:
            reportcmd(f"systemctl restart wpa_supplicant@{self.pd.netdev}", msg=f"Restart wpa_supplicant@{self.pd.netdev} to use new SSID/password")
        # Wait for the network to come online
        myipaddr = ""
        for i in range(1, self.pd.settings['dhcpwait']):
            s = gocmd(f"ip -br -o -f inet addr show dev {self.pd.netdev}") 
            if s != "": myipaddr = ' '.join(s.split()).split(' ')[2].split('/')[0]
            if myipaddr != "" and not myipaddr.startswith("169.254"): break
            syslogger(f"Waiting ({i} of {self.pd.settings['dhcpwait']}) for {self.pd.netdev} to obtain an IP address")
            time.sleep(1)
        self.pd.wlanip = myipaddr
        if self.pd.wlanip != "":
            syslogger(f"Got IP address {self.pd.wlanip}")
            if self.pd.settings['ckinternet']  == "on" and self.pd.wlanip != "":
                syslogger("Test Internet accessibility")
                if iponline("1.1.1.1", pingcount=5):
                    syslogger("Internet is Accessible")
                    self.pd.iconnected = True
                else:
                    syslogger("Internet is Not Accessible")
            updatewifi(pd)
            ledresult = "ResultGood"
        else:
            syslogger(f"Did not obtain an IP address")
            ledresult = "ResultBad"
        self.pd.isresult = True
        pd.writel10n(self.pd.settings['keymap'], self.pd.settings['locale'], self.pd.settings['timezone'])
        self.pd.leds.setsequence(self.pd.ledseq[ledresult])
        return

class sdmRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, pd, *args, **kwargs):
        self.pd = pd
        # This seems to be getting ConnectionResetError and BrokenPipeError at times
        # Ignore them until better understood, since this is relatively stateless
        try:
            super().__init__(*args, **kwargs)
        except (ConnectionResetError, BrokenPipeError):
            syslogger("Got ConnectionResetError or BrokenPipeError")
            pass

    def __del__(self):
        if self.pd.debug: syslogger("http request handler object deleted")

    def _set_response(self, rcode=200):
        self.send_response(rcode)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        return
        
    def log_message(self, *args, **kwargs):
        # Prevents debug output from going to stderr 
        return

    def _adderror(self, oldstring, newstring):
        syslogger(f"Error: {newstring}")
        if oldstring == "":
            return newstring
        return  f"{oldstring}<br>{newstring}"

    def _buildresponse(self, pd, redolink=False):
        response = f"<html><body><h1>WiFi Configuration Results for host {pd.hostname}</h1>"
        if self.pd.connected:
            response = f"{response}<h2>Obtained IP Address {self.pd.wlanip} via WiFi SSID '{self.pd.settings['ssid']}'<br></h2>"
        else:
            response = f"{response}<h2>WiFi Did NOT Connect Successfully</h2>"
        if self.pd.iconnected:
            response = f"{response}<h2>Internet IS Accessible</h2>"
        else:
            if not self.pd.settings['ckinternet'] == "on":
                response = f"{response}<h2>Internet Accessibility was not tested</h2>"
            else:
                response = f"{response}<h2>Internet is NOT Accessible</h2>"
        if redolink:
            response = f"{response}<h2><a href=\"http://{self.pd.apip}/\" target=\"_blank\">Restart Captive Portal</a></h2>"
            response = f"{response}<h2><a href=\"http://{self.pd.apip}/giveup\" target=\"_blank\">Cancel Captive Portal</a></h2>"
        return f"{response}</body></html>"

    def _write_response(self, htmltext):
        self._set_response()
        return self.wfile.write(htmltext.encode('utf-8'))
    
    def _setstop(self, pd):
        self.pd.runflag = False

    def _notriesleft(self, status):
        self.pd.status = status
        self.pd.retries -= 1
        if self.pd.retries == 0:
            return True
        return False

    def do_GET(self):
        if not self.pd.atimer is None:
            self.pd.atimer.reset()
        else:
            syslogger("atimer is None in do_GET")
        if not 'favicon' in self.path:
            syslogger(f"Received message {self.path}")
        if "/formsubmit" in self.path:
            query_items = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            for i in self.pd.settings:
                if i in query_items: self.pd.settings[i] = query_items[i][0].strip()
            if self.pd.defaults != "":
                default_items = parse_qs(urlparse(pd.defaults).query, keep_blank_values=True)
                fover = False
                if "override" in default_items: fover = True
                for i in self.pd.settings:
                    if i in default_items:
                        if default_items[i][0] != "":
                            if self.pd.settings[i] == "" or fover:
                                if self.pd.debug: syslogger(f"Update Setting {i} from defaults")
                                self.pd.settings[i] = default_items[i][0].strip()
            self.pd.settings['wificountry'] = self.pd.settings['wificountry'].upper()
            self.pd.settings['keymap'] = self.pd.settings['keymap'].lower()

            # Validate inputs
            syslogger("Validate form data")
            self.pd.allerrors = ""
            if self.pd.settings['ssid'] == "":
                self.pd.allerrors = self._adderror(self.pd.allerrors, "SSID cannot be blank")
            if self.pd.settings['password'] == "":
                self.pd.allerrors = self._adderror(self.pd.allerrors, "Password cannot be blank")
            else:
                if len(self.pd.settings['password']) < 8 or len(self.pd.settings['password']) > 63:
                    self.pd.allerrors = self._adderror(self.pd.allerrors, "Password must be between 8-63 characters")
            if self.pd.settings['keymap'] != "":
                if not runcmd(f"grep \"^  {self.pd.settings['keymap']} \" /usr/share/doc/keyboard-configuration/xorg.lst", nolog=True):
                    self.pd.allerrors = self._adderror(self.pd.allerrors, f"Unrecognized keymap '{self.pd.settings['keymap']}'")
            if self.pd.settings['locale'] != "":
                if not runcmd(f"grep \"^{self.pd.settings['locale']}\" /usr/share/i18n/SUPPORTED", nolog=True):
                    self.pd.allerrors = self._adderror(self.pd.allerrors, f"Unrecognized locale '{self.pd.settings['locale']}'")
            if self.pd.settings['wificountry'] != "":
                self.pd.settings['wificountry'] = self.pd.settings['wificountry'].upper()
                if not runcmd(f"grep \"^{self.pd.settings['wificountry']}\" /usr/share/zoneinfo/iso3166.tab", nolog=True):
                    self.pd.allerrors = self._adderror(self.pd.allerrors, f"Unrecognized WiFi Country '{self.pd.settings['wificountry']}'")
            if self.pd.settings['timezone'] != "":
                if not os.path.isfile(f"/usr/share/zoneinfo/{self.pd.settings['timezone']}"):
                    self.pd.allerrors = self._adderror(self.pd.allerrors, f"Unrecognized Timezone '{self.pd.settings['timezone']}'")
            if self.pd.settings['dhcpwait'] != "":
                try:
                    dwait = self.pd.settings['dhcpwait']
                    self.pd.settings['dhcpwait'] = int(dwait)
                except:
                    self.pd.allerrors = self._adderror(self.pd.allerrors, f"dhcpwait value '{dwait}' is not numeric")
                    self.pd.settings['dhcpwait'] = 60
            else:
                self.pd.settings['dhcpwait'] = 60
            if self.pd.allerrors != "":
                syslogger("Errors were found")
                self.pd.allerrors = f"<html><body><style>body {{ font-size: 30px; }}</style><h1>Errors Found for host {self.pd.hostname}</h1><h2>{self.pd.allerrors}</h2>"
                self.pd.allerrors = f"{self.pd.allerrors}<h2><a href=\"http://{self.pd.apip}/\" target=\"_blank\">Restart Captive Portal</a></h2>"
                self.pd.allerrors = f"{self.pd.allerrors}<h2><a href=\"http://{self.pd.apip}/giveup\" target=\"_blank\">Cancel Captive Portal</a></h2>"
                self.pd.allerrors = f"{self.pd.allerrors}</body></html>"
                syslogger("Send error report message")
                self._write_response(self.pd.allerrors)
            else:
                self.pd.formdone = True
                syslogger("Form input validation complete")
                if self.pd.settings['validate'] == "on":
                    curpm = self.pd.getwlanpm(self.pd.netdev)
                    if self.pd.settings['wifipower'] == "on" and curpm != "on":
                        reportcmd(f"iwconfig {self.pd.netdev} power on", msg=f"Set {self.pd.netdev} Power Management on")
                    else:
                        if self.pd.settings['wifipower'] == "off" and curpm == "on":
                            reportcmd(f"iwconfig {self.pd.netdev} power off", msg=f"Set {self.pd.netdev} Power Management off")
                    syslogger("Send redirect to testinprogress")
                    self.send_response(302)
                    self.send_header('Location', f"http://{self.pd.apip}/testinprogress")
                    self.end_headers()
                    time.sleep(3.0)  # Not really sleeping here?
                    syslogger("Start Validate WiFi configuration thread")
                    self.pd.netops = None         # Delete any previous instantiation
                    self.pd.netops = Netops(pd)
                    self.pd.netops.start()
                else:
                    syslogger("Write WiFi configuration with No Validation")
                    self.pd.writewpaconf()
                    syslogger("Send notValidated message")
                    self._write_response(self.pd.pdmsgs.notValidated.format(self.pd.hostname))
                    self._notriesleft(self.pd.errors['notestdone'])
                    self._setstop(self.pd)
        elif self.path == "/" or "/hotspot-detect.html" in self.path:
            syslogger(f"Send greeting page to remote from query to {self.path}")
            self._write_response(self.pd.pdmsgs.greeting_page.format(self.pd.hostname, self.pd.hostname, self.pd.apip, self.pd.apip))
        elif "/testinprogress" in self.path:
            syslogger("Send testinprogress page")
            self._write_response(self.pd.pdmsgs.testinprogress_page.format(self.pd.hostname, self.pd.apip))
        elif "/giveup" in self.path:
            syslogger("Received manual 'give up' message")
            self.pd.status = self.pd.errors['manualgiveup']
            self._write_response(self.pd.pdmsgs.giveup_page.format(self.pd.hostname))
            self._setstop(pd)
        elif "/webform" in self.path:
            query_items = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            getssids = query_items['findssids'][0].strip() if 'findssids' in query_items else ""
            ssidlist = getssidlist() if getssids == "on" else ""
            syslogger("Send form page to remote")
            self._write_response(self.pd.pdmsgs.web_form.format(self.pd.hostname, ssidlist))
        elif "/checkresult" in self.path:
            if not self.pd.formdone:
                syslogger("Checkresult called before form done")
                self._write_response(self.pd.notstarted_page(self.pd.hostname, self.pd.apip))
                return
            if not self.pd.isresult:
                syslogger("Checkresult called before result ready")
                self._write_response(self.pd.pdmsgs.wait_page.format(self.pd.hostname, self.pd.apip))
                return
            # get my ip address and error if it didn't connect
            myipaddr = self.pd.wlanip
            if myipaddr == "" or myipaddr.startswith("169.254"):
                syslogger("Failed to obtain an IP Address")
                syslogger("Send built response message")
                self._write_response(self._buildresponse(pd, redolink=True))
                self.pd.inprogress = False
                if self._notriesleft(self.pd.errors['noconnect']):
                    self._setstop(pd)
                return
            else:
                syslogger(f"Obtained IP Address {myipaddr}")
                self.pd.connected = True
                self.pd.wlanip = myipaddr
            if self.pd.settings['ckinternet'] == "on":
                if self.pd.iconnected:
                    syslogger("Internet is Accessible")
                    syslogger("Send built response message")
                    self._write_response(self._buildresponse(pd))
                    self.pd.status = self.pd.errors['success']
                    self.pd.inprogress = False
                    self._setstop(pd)
                else:
                    syslogger("Internet is Not Accessible")
                    syslogger("Send built response message")
                    self._write_response(self._buildresponse(pd))
                    self.pd.inprogress = False
                    self.pd.leds.setsequence(self.pd.ledseq['APon'])
                    if self._notriesleft(self.pd.errors['nointernet']):
                        self._setstop(pd)
            else:
                syslogger("WiFi Operational, no Internet check done")
                syslogger("Send built response message")
                self.pd.status = self.pd.errors['notestdone']
                self._write_response(self._buildresponse(self.pd))
                self.pd.inprogress = False
                self._notriesleft(self.pd.errors['notestdone'])
                syslogger("Update /etc/wpa_supplicant/wpa_supplicant.conf")
                updatewifi(pd)
                pd.writel10n(self.pd.settings['keymap'], self.pd.settings['locale'], self.pd.settings['timezone'])
                self.pd.leds.setsequence(self.pd.ledseq['ResultGood'])
                self._setstop(pd)
        return

def updatewifi(pd):
    return
    if pd.usenm:
        reportcmd("nmcli c up sdmap", "Restart Access Point")
    else:
        syslogger("Update /etc/wpa_supplicant/wpa_supplicant.conf")
        qdelfile("/etc/wpa_supplicant/wpa_supplicant.conf")
        qcopyfile(f"/etc/wpa_supplicant/wpa_supplicant-{self.pd.netdev}.conf", "/etc/wpa_supplicant/wpa_supplicant.conf")

def docleanup(pd, resetcmd=False):
    if pd.usenm:
        runcmd(f"nmcli c down sdmap")
        runcmd(f"iw dev {pd.uapname} del")
        runcmd(f"systemctl stop wpa_supplicant@{pd.netdev}", msg=f"Stop {pd.netdev} wpa_supplicant")
        #qdelfile(f"/etc/NetworkManager/system-connections/sdmap.nmconnection")
        #runcmd("nmcli c reload", "Reload NetworkManager connections")
        #runcmd(f"nmcli c up {pd.netdev}")
    else:
        if gocmd(f"iw dev {pd.apname} info") != "":
            if f"tmp-{pd.facname}" in gocmd(f"ip netns"):
                runcmd(f"iw {pd.phydev} set netns name {pd.netns}", msg=f"Delete Access Point {pd.apname}")
                runcmd(f"ip netns exec {pd.netns} iw dev {pd.apname} del")
                runcmd(f"ip netns exec {pd.netns} iw {pd.phydev} set netns 1") # Set back to primary namespace
        runcmd(f"iw dev {pd.apname} del")                         # Just in case
        runcmd(f"ip netns del {pd.netns}")                                         # And delete temp ns, no longer needed
        runcmd(f"systemctl stop wpa_supplicant@{pd.apname}", msg=f"Stop {pd.apname} wpa_supplicant")
        runcmd(f"systemctl stop wpa_supplicant@{pd.netdev}", msg=f"Stop {pd.netdev} wpa_supplicant")
        qdelfile(f"/var/run/wpa_supplicant/{pd.apname}")
        qdelfile(f"/etc/systemd/network/{pd.facname}-{pd.apname}.network")
        qdelfile(f"/etc/systemd/network/{pd.facname}-{pd.netdev}.network")
        qdelfile(f"/etc/wpa_supplicant/wpa_supplicant-{pd.apname}.conf")
        qdelfile(f"/etc/wpa_supplicant/wpa_supplicant-{pd.netdev}.conf")
        qdelfile(f"/etc/NetworkManager/system-connections/sdmtemp.nmconnection")
        syslogger(f"Reload systemd and restart systemd-networkd and {pd.dhcp.dhcpclient}")
        if pd.sdndrunning:
            reportcmd("systemctl daemon-reload")
            reportcmd("systemctl restart systemd-networkd")
        else:
            reportcmd("systemctl stop systemd-networkd.socket")
            reportcmd("systemctl stop systemd-networkd")
            reportcmd("systemctl daemon-reload")
        #Toggle the netdev network. Seems to work better. Or maybe not. Keep the code, commented out, for now
        #reportcmd(f"networkctl down {pd.netdev}", msg=f"Toggle {pd.netdev} offline/online before {pd.dhcp.dhcpclient} restart")
        #reportcmd(f"networkctl up {pd.netdev}")
        pd.dhcp.restartclient()

def resetnet(pd):
    syslogger("Reset Captive Portal WiFi Network")
    docleanup(pd, resetcmd=True)
    syslogger("Captive Portal WiFi Network Reset Complete")
    
def runclean(pd):
    # Incomplete, but better than a stack trace
    pd.runflag = False
    if not pd.leds is None: pd.leds.setstopled()
    pd.leds = pd.httpd = pd.atimer = pd.netops = None
    docleanup(pd)

def apconfigure(pd):
    if pd.usenm:
        #**
        # iw dev wlan0 interface add uap0 type __ap
        #
        # nmcli con add type wifi ifname wlan0 mode ap con-name sdm ssid sdm-pt
        # nmcli con modify sdm wifi.band bg autoconnect false wifi.cloned-mac-address 00:12:34:56:78:9a
        # nmcli con modify sdm wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.group ccmp wifi-sec.pairwise ccmp
        # nmcli con modify sdm wifi-sec.psk "password"
        # nmcli con modify sdm ipv4.method shared ipv4.address 10.1.1.1/24
        # nmcli con modify sdm ipv6.method disabled
        # nmcli con modify sdm connection.interface-name uap0
        # nmcli con up sdm

        with open(f"/etc/NetworkManager/system-connections/sdmap.nmconnection", 'w') as f:
            f.write(f"[connection]\n\
id=sdmap\n\
uuid={uuid.uuid4()}\n\
type=wifi\n\
autoconnect=false\n\
interface-name={pd.uapname}\n\
\n\
[wifi]\n\
band=bg\n\
cloned-mac-address=00:12:34:56:78:9A\n\
mode=ap\n\
ssid={pd.hostname}-{pd.apssid}\n\
\n\
[wifi-security]\n\
key-mgmt=wpa-psk\n\
psk=password\n\
\n\
[ipv4]\n\
address1=10.1.1.1/24\n\
method=shared\n\
\n\
[ipv6]\n\
addr-gen-mode=default\n\
method=disabled\n")
        os.chmod("/etc/NetworkManager/system-connections/sdmap.nmconnection", 0o600)
        #
        # dnsmasq configuration
        #
        with open(f"/etc/NetworkManager/conf.d/sdm-dnsconfig.conf", 'w') as f:
            f.write(f"dns=dnsmasq\n")
        with open(f"/etc/NetworkManager/dnsmasq.d/redirect.conf", 'w') as f:
            f.write(f"address=/#/10.1.1.1\n")
        runcmd(f"iw dev {pd.uapname} del")
        reportcmd(f"iw dev {pd.netdev} interface add {pd.uapname} type __ap", "Create AP network device")
        reportcmd("nmcli c reload", "Reload NetworkManager connections")
        reportcmd("nmcli c up sdmap", "Start Access Point")
    else:
        pd.dhcp.stopclient()
        reportcmd(f"systemctl stop systemd-networkd.socket", msg="Stop systemd-networkd")
        reportcmd(f"systemctl stop systemd-networkd")
        reportcmd(f"ip netns add {pd.netns}", msg="Reconfigure network to create Access Point")
        reportcmd(f"iw {pd.phydev} set netns name {pd.netns}")
        reportcmd(f"ip netns exec {pd.netns} iw phy {pd.phydev} interface add {pd.apname} type __ap")
        syslogger(f"Write /etc/systemd/network/{pd.facname}-{pd.apname}.network and /etc/systemd/network/{pd.facname}-{pd.netdev}.network")
        pd.writenetconfig()
        syslogger(f"Write /etc/wpa_supplicant/wpa_supplicant-{pd.apname}.conf")
        pd.settings['ssid'] = "sdmtemp"
        pd.settings['password'] = "sdmtemp"
        pd.writewpaconf(wlan=pd.netdev)
        pd.writeapwpaconf()
        reportcmd(f"ip netns exec {pd.netns} iw {pd.phydev} set netns 1") # Set back to primary namespace
        qdelfile(f"/var/run/wpa_supplicant/{pd.apname}")
        reportcmd(f"systemctl daemon-reload", msg='Do daemon-reload and start systemd-networkd')
        reportcmd("systemctl start systemd-networkd")
        reportcmd(f"systemctl start wpa_supplicant@{pd.apname}", msg=f"Start wpa_supplicant@{pd.apname}")
        waitapip(pd.apip)

def runserver(pd):
    syslogger("Portal network reconfiguration")
    pd.usenm = True
    apconfigure(pd)
    pd.leds.setsequence(pd.ledseq['APon'])
    syslogger("Start HTTP Server")
    handler = partial(sdmRequestHandler, pd)
    pd.httpd = ThreadingHTTPServer((pd.apip, 80), handler)
    pd.atimer.start()
    while pd.runflag and pd.retries > 0:
        pd.httpd.handle_request()
    syslogger("Reset Captive Portal WiFi Network")
    pd.leds.setsequence(pd.ledseq['Cleanup'])
    docleanup(pd)
    pd.leds.setstopled()
    pd.leds = pd.httpd = pd.atimer = pd.netops = None
    syslogger("Captive Portal Complete")
    return pd.status

if __name__ == "__main__":
    pd = cpcontrol()
    parser = argparse.ArgumentParser(prog='cportal')
    parser.add_argument('--apssid', help="SSID name for Access Point")
    parser.add_argument('--apip', help="IP Address to use for Access Point")
    parser.add_argument('--country', default="US", help="Default WiFi country if user doesn't specify")
    parser.add_argument('--defaults', help="Provide a file with default settings")
    parser.add_argument('--reset', help="Reset networking configuration to non-portal state", action='store_true')
    parser.add_argument('--debug', help="Print logged messages on console also", action='store_true')
    parser.add_argument('--facility', help="Facility name to use instead of 'sdm'")
    parser.add_argument('--l10nhandler', help="Full path to script to handle Localization data")
    parser.add_argument('--retries', default="5", help="Stop Captive Portal after this many failed retries [Default:5]")
    parser.add_argument('--sdm', help="Invoked from sdm", action='store_true')
    parser.add_argument('--timeout', default="900", help="No activity timeout [Default:900 seconds]")
    parser.add_argument('--web-msgs', help="Replace Web HTML with HTML of your own choosing")
    parser.add_argument('--wlan', default="wlan0", help="Specify WiFi device [Default:wlan0]")
    args = parser.parse_args()
    pd.args = args
    pd.apssid = args.apssid if args.apssid != None else "sdm"
    pd.apip = args.apip if args.apip != None else "10.1.1.1"
    pd.debug = args.debug
    pd.facname = "sdm" if args.facility == None else args.facility
    pd.apname = f"{pd.facname}0"
    pd.netns = f"tmp-{pd.facname}"
    pd.l10nhandler = "" if args.l10nhandler == None else args.l10nhandler
    pd.sdm = args.sdm
    syslog.openlog(ident="sdm-cportal")
    if not args.reset:
        if os.path.exists(f"/sys/class/net/{args.wlan}"):
            pd.phydev = read1stline(f"/sys/class/net/{args.wlan}/phy80211/name")
            pd.netdev = args.wlan
        if pd.netdev == "" or pd.phydev == "":
            pxsyslogger(f"? Unrecognized WiFi device {args.wlan}")
    else:
        pd.netdev = args.wlan
    
    pd.retries = getintval(args.retries, '--retries')
    pd.timeout = getintval(args.timeout, '--timeout')
    pd.dhcp = DHCPClient(pd)
    if args.reset:
        resetnet(pd)
        raise SystemExit(0)
    if not args.defaults is None:
        if not os.path.exists(args.defaults): pxsyslogger(f"? Defaults file '{args.defaults}' not found")
        pd.defaults = read1stline(args.defaults)
        try:
            query_items = parse_qs(urlparse(pd.defaults).query, keep_blank_values=True)
        except ValueError:
            pxsyslogger("? Unable to parse defaults file '{args.defaults}'")
    syslogger("Start Captive Portal")
    pd.pdmsgs = htmsgs()
    pd.leds = LEDflash(pd)
    pd.atimer = ATimer(pd)
    pd.leds.setsequence(pd.ledseq['APoff'])
    pd.leds.start()
    if args.web_msgs != None:
        msgfn = '.'.join(os.path.basename(args.web_msgs).split('.')[:-1])
        # ** UNTESTED how hard to look for the file? ?? if web_msgs has a path, strip the path, sys.path.append 
        if os.path.exists(args.web_msgs):
            impmsg = __import__(msgfn)
            del pd.pdmsgs
            pd.pdmsgs = impmsg.htmsgs()
    try:
        runserver(pd)
    except KeyboardInterrupt:
        print(f"CTRL/C clean up and exit")
        pd.status = 987
        runclean(pd)
    except:
        runclean(pd)
        perrorexit(f"? Caught unhandled exception")
    time.sleep(0.5)
    syslogger("Captive Portal Exit")
    raise SystemExit(pd.status)
