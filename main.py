# clean.py Test of asynchronous mqtt client with clean session.
# (C) Copyright Peter Hinch 2017-2019.
# Released under the MIT licence.

# Public brokers https://github.com/mqtt/mqtt.github.io/wiki/public_brokers

# The use of clean_session means that after a connection failure subscriptions
# must be renewed (MQTT spec 3.1.2.4). This is done by the connect handler.
# Note that publications issued during the outage will be missed. If this is
# an issue see unclean.py.

# red LED: ON == WiFi fail
# blue LED heartbeat: demonstrates scheduler is running.
import machine
from machine import Pin
from mqtt_as import MQTTClient
from mqtt_local import wifi_led, blue_led, config
import uasyncio as asyncio
import os


openSTAT = Pin(16, Pin.IN, Pin.PULL_DOWN)
closeSTAT = Pin(17, Pin.IN, Pin.PULL_DOWN)
objDTC = Pin(18, Pin.IN, Pin.PULL_DOWN)
CMDopen = Pin(19, Pin.OUT)
CMDclose = Pin(20, Pin.OUT)
CMDstop = Pin(21, Pin.OUT)




#Log declarations
rtc=machine.RTC()
FileName = 'log.txt'

#Logging
try:
    os.stat(FileName)
    print("File Exists")
except:
    print("File Missing")
    f = open(FileName, "w")
    f.close()
    
def log(loginfo:str):
    # Format the timestamp
    LED_FileWrite(1)
    timestamp=rtc.datetime()
    timestring="%04d-%02d-%02d %02d:%02d:%02d"%(timestamp[0:3] + timestamp[4:7])
    # Check the file size
    filestats = os.stat(FileName)
    filesize = filestats[6]
    LED_FileWrite(0)

    if(filesize<200000):
        try:
            
            log = timestring +" "+ str(filesize) +" "+ loginfo +"\n"
            print(log)
            with open(FileName, "at") as f:
                f.write(log)
            
        except:
            print("Problem saving file")


#MQTT Details

MACHINE_ID = "_gate_control"
DEVICE_ID = "pico_w"
CLIENT_ID = str(DEVICE_ID)+str((MACHINE_ID))#[14:-1])
SUBSCRIBE_TOPIC = str(CLIENT_ID)+"/Command"
PUBLISH_TOPIC1 = str(CLIENT_ID)+"/Command"
PUBLISH_TOPIC2 = str(CLIENT_ID)+"/Status"
PUBLISH_TOPIC3 = str(CLIENT_ID)+"/Info"

openCMD = False
closeCMD = False
stopCMD = False

# Subscription callback
def sub_cb(topic, msg, retained):
    
    global openCMD
    global closeCMD
    global stopCMD
    
    if topic.decode() == SUBSCRIBE_TOPIC +"/open":
        openCMD = int(msg.decode())
    
              
    if topic.decode() == SUBSCRIBE_TOPIC +"/close":
        closeCMD = int(msg.decode())
        
    if topic.decode() == SUBSCRIBE_TOPIC +"/stop":
        stopCMD = int(msg.decode())

# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        blue_led(s)
        s = not s

async def wifi_han(state):
    wifi_led(not state)
    print('Wifi is ', 'up' if state else 'down')
    await asyncio.sleep(1)


async def main(client):
    try:
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
    
    while True:
        await asyncio.sleep(1)
        await client.subscribe((SUBSCRIBE_TOPIC +"/open"), 1)
        await client.subscribe((SUBSCRIBE_TOPIC +"/close"), 1)
        await client.subscribe((SUBSCRIBE_TOPIC +"/stop"), 1)
        # If WiFi is down the following will pause for the duration.
      
        
        if openCMD and not closeCMD and not stopCMD:
            CMDopen(1)
            asyncio.sleep(1)
        else:
            CMDopen(0)
        await client.publish((PUBLISH_TOPIC1 +"/open"), f"0", qos=1)
        
        
        if  closeCMD and not openCMD and not stopCMD:
            CMDclose(1)
            asyncio.sleep(1)
        else:
            CMDclose(0)
        await client.publish((PUBLISH_TOPIC1 +"/close"), f"0", qos=1)
        
        if  stopCMD:
            CMDstop(1)
            asyncio.sleep(1)
        else:
            CMDstop(0)
        await client.publish((PUBLISH_TOPIC1 +"/stop"), f"0", qos=1)
        
        if openSTAT:
            await client.publish((PUBLISH_TOPIC2 +"/open"), f"1", qos=1)
        else:
            await client.publish((PUBLISH_TOPIC2 +"/open"), f"0", qos=1)
        
        if closeSTAT:
            await client.publish((PUBLISH_TOPIC2 +"/close"), f"1", qos=1)
        else:
            await client.publish((PUBLISH_TOPIC2 +"/close"), f"0", qos=1)

        if objDTC:
            await client.publish((PUBLISH_TOPIC2 +"/objDTC"), f"1", qos=1)
        else:
            await client.publish((PUBLISH_TOPIC2 +"/objDTC"), f"0", qos=1)

# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['connect_coro'] = conn_han
config['clean'] = False

# Set up client
MQTTClient.DEBUG = False  # Optional
client = MQTTClient(config)

asyncio.create_task(heartbeat())
try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()
