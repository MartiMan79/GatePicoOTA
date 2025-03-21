import gc
from log import logger
import machine
from machine import Pin, RTC
from mqtt_as import MQTTClient, RP2
from mqtt_local import config
import network
from ntptime import settime
import os
from ota import OTAUpdater
import sys
import uasyncio as asyncio
import time


if RP2:
    from sys import implementation
    

# define motor controller pins
openSTAT = Pin(16, Pin.IN, Pin.PULL_DOWN)
closeSTAT = Pin(17, Pin.IN, Pin.PULL_DOWN)
objDTC = Pin(18, Pin.IN, Pin.PULL_DOWN)
CMDopen = Pin(19, Pin.OUT)
CMDclose = Pin(20, Pin.OUT)
CMDstop = Pin(21, Pin.OUT)
LED = machine.Pin("LED",machine.Pin.OUT)


#MQTT Details
CLIENT_ID = config["client_id"]

SUBSCRIBE_TOPIC = str(CLIENT_ID)+"/Command"
PUBLISH_TOPIC1 = str(CLIENT_ID)+"/Command"
PUBLISH_TOPIC2 = str(CLIENT_ID)+"/Status"
PUBLISH_TOPIC3 = str(CLIENT_ID)+"/Info"


# Global values
gc_text = ''
DATAFILENAME = 'data.txt'
LOGFILENAME = 'debug.log'
ERRORLOGFILENAME = 'errorlog.txt'

# Variables
openCMD = False
closeCMD = False
stopCMD = False

# HTML file
html = """<!DOCTYPE html>
<html>
    <head> <title>Gate controller</title> </head>
    <body> <h1>Entrance gate control</h1>
        <h3>%s</h3>
        <h4>%s</h4>
        <pre>%s</pre>
    </body>
</html>
"""

async def log_handling():

    local_time = time.localtime()
    global timestamp
    record("power-up @ (%d, %d, %d, %d, %d, %d, %d, %d)" % local_time)

    try:
        
        y = local_time[0]  # curr year
        mo = local_time[1] # current month
        d = local_time[2]  # current day
        h = local_time[3]  # curr hour
        m = local_time[4]  # curr minute
        s = local_time[5]  # curr second
        
        timestamp = f"{h:02}:{m:02}:{s:02}"
        # Test WiFi connection twice per minute
        if s in (15, 45):
            if not wifi_han(state):
                record(f"{timestamp} WiFi not connected")
                
            elif wifi_han(state):
                sync_rtc_to_ntp()
                await asyncio.sleep(1)
        
        # Print time on 30 min intervals
        if s in (1,) and not m % 30:
            try:
                record(f"datapoint @ {timestamp}")
                
                gc_text = f"free: {str(gc.mem_free())}\n"
                gc.collect()
            except Exception as e:
                with open(ERRORLOGFILENAME, 'a') as file:
                    file.write(f"error printing: {repr(e)}\n")

        # Once daily (during the wee hours)
        if h == 2 and m == 10 and s == 1:
            
            # Read lines from previous day
            with open(DATAFILENAME) as f:
                lines = f.readlines()

            # first line is yesterday's date
            yesterdate = lines[0].split()[-1].strip()

            # cull all lines containing '@'
            lines = [line
                     for line in lines
                     if '@' not in line]
            
            # Log lines from previous day
            with open(LOGFILENAME, 'a') as f:
                for line in lines:
                    f.write(line)
            
            # Start a new data file for today
            with open(DATAFILENAME, 'w') as file:
                file.write('Date: %d/%d/%d\n' % (mo, d, y))

    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"main loop error: {str(e)}\n")



async def serve_client(reader, writer):
    
    
    try:
        dprint("Client connected")
        request_line = await reader.readline()
        dprint("Request:", request_line)
        
        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass
        
        gc.collect()
        m = gc.mem_free()
        dprint('mem free', m)
        
        version = f"MicroPython Version: {sys.version}"

        if '/log' in request_line.split()[1]:
            with open(LOGFILENAME) as file:
                data = file.read()
            heading = "Debug"
            dprint('log demanded')
        elif '/err' in request_line.split()[1]:
            with open(ERRORLOGFILENAME) as file:
                data = file.read()
            heading = "ERRORS"
        else:
            with open(DATAFILENAME) as file:
                data = file.read()
            heading = "Append '/log' or '/err' to URL to see log file or error log"

        data += gc_text

        response = html % (heading, version, data)
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        writer.write(response)

        await writer.drain()
        await writer.wait_closed()
        dprint("Client disconnected")
    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            
            file.write(f"serve_client error @ {timestamp}: {str(e)}\n")


def record(line):
    """Combined print and append to data file."""
    print(line)
    line += '\n'
    with open(DATAFILENAME, 'a') as file:
        file.write(line)

def dprint(*args):
        logger.debug(*args)


# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        LED(s)
        s = not s

async def wifi_han(state):
    s = "rssi: {}dB"
    LED(not state)
    if state:
        dprint('Wifi is up')
        dprint(s.format(rssi))
    else:
        dprint('Wifi is down')    
    await asyncio.sleep(1)

async def get_rssi():
    global rssi
    s = network.WLAN()
    ssid = config["ssid"].encode("UTF8")
    #while True:
    try:
        while True:
            
            rssi = [x[3] for x in s.scan() if x[0] == ssid][0]
            
            break
        
    except IndexError:  # ssid not found.
        rssi = -199
    await asyncio.sleep(30)

async def get_ntp():
    
    try:
    
        settime()
        rtc = machine.RTC()
        utc_shift = 1

        tm = time.localtime(time.mktime(time.localtime()) + utc_shift*3600)
        tm = tm[0:3] + (0,) + tm[3:6] + (0,)
        rtc.datetime(tm)
    
    except OSError as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"OSError while trying to set time: {str(e)}\n")        
        
    dprint("machine time is:",(time.localtime()))

# If you connect with clean_session True, must re-subscribe (MQTT spec 3.1.2.4)
async def conn_han(client):
    
    await client.subscribe((SUBSCRIBE_TOPIC +"/open"), 1)
    await client.subscribe((SUBSCRIBE_TOPIC +"/close"), 1)
    await client.subscribe((SUBSCRIBE_TOPIC +"/stop"), 1)

# Subscription callback
def sub_cb(topic, msg, retained):

    global openCMD
    global closeCMD
    global stopCMD

    dprint(f'Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')

    
    if topic.decode() == SUBSCRIBE_TOPIC +"/open":
        openCMD = int(msg.decode())
              
    if topic.decode() == SUBSCRIBE_TOPIC +"/close":
        closeCMD = int(msg.decode())
        
    if topic.decode() == SUBSCRIBE_TOPIC +"/stop":
        stopCMD = int(msg.decode())
        
async def comm(client):
    
    oldValOpen = False
    oldValClose = False
    oldValObjDTC = False
    
    while True:
        # If WiFi is down the following will pause for the duration.
      
        
        if openCMD and not closeCMD and not stopCMD:
            dprint('Open command received')
            CMDopen(1)
            asyncio.sleep(1)
        else:
            CMDopen(0)
        await client.publish((PUBLISH_TOPIC1 +"/open"), f"0", qos=1)
        
        
        if  closeCMD and not openCMD and not stopCMD:
            dprint('Close command received')
            CMDclose(1)
            
        else:
            CMDclose(0)
        asyncio.sleep(1)
        await client.publish((PUBLISH_TOPIC1 +"/close"), f"0", qos=1)
        
        if  stopCMD:
            dprint('Stop command received')
            CMDstop(1)
            asyncio.sleep(1)
        else:
            CMDstop(0)
        await client.publish((PUBLISH_TOPIC1 +"/stop"), f"0", qos=1)
        
        
        if openSTAT() and not oldValOpen:
            dprint("Gate is open")
            await client.publish((PUBLISH_TOPIC2 +"/open"), f"1", qos=1)
            oldValOpen = True
            
        elif not openSTAT() and oldValOpen:
            await client.publish((PUBLISH_TOPIC2 +"/open"), f"0", qos=1)
            oldValOpen = False
         
    
    
        if closeSTAT() and not oldValClose:
            dprint("Gate is closed")
            await client.publish((PUBLISH_TOPIC2 +"/close"), f"1", qos=1)
            oldValClose = True
            
        elif not closeSTAT() and oldValClose:
            await client.publish((PUBLISH_TOPIC2 +"/close"), f"0", qos=1)
            oldValClose = False



        if objDTC() and not oldValObjDTC:
            dprint("Object detected")
            await client.publish((PUBLISH_TOPIC2 +"/objDTC"), f"1", qos=1)
            oldValObjDTC = True
            
        elif not objDTC() and oldValObjDTC:
            await client.publish((PUBLISH_TOPIC2 +"/objDTC"), f"0", qos=1)
            oldValObjDTC = False


async def OTA():
    
    # Check for OTA updates
    repo_name = "GatePicoOTA"
    branch = "refs/heads/main"
    firmware_url = f"https://github.com/MartiMan79/{repo_name}/{branch}/"
    ota_updater = OTAUpdater(firmware_url,
                             "main.py",
                             "ota.py",
                             "log.py",
                             "lib/ntptime.py",
                             "lib/logging/handlers.py",
                             "lib/logging/__init__.py",
                             )
    ota_updater.download_and_install_update_if_available()     

async def main(client):

  
    try:
        await client.connect()
        await client.publish(PUBLISH_TOPIC3, f'Connected', qos=1)


       
    except OSError:
        dprint('Connection failed.')
        return
    
    
    await get_ntp()
    await OTA()
    dprint("Startup ready")

    while True:

        await comm(client)
        

# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['connect_coro'] = conn_han
config['clean'] = True
config['keepalive'] = 120


# Set up client
MQTTClient.DEBUG = False  # Optional
client = MQTTClient(config)

asyncio.create_task(heartbeat())
asyncio.create_task(get_rssi())
asyncio.create_task(log_handling())
asyncio.create_task(asyncio.start_server(serve_client, "0.0.0.0", 80))

try:
    asyncio.run(main(client))
    
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop() 
