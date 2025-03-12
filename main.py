from machine import Pin
from time import sleep

print('Microcontrollerslab.com')

led = Pin(20, Pin.OUT)    # 14 number in is Output



led.value(1)             # led will turn ON
sleep(5)                 # if push_button not pressed
led.value(0)             # led will turn OFF