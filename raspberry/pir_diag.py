from gpiozero import DigitalInputDevice
from time import sleep

pir = DigitalInputDevice(17, pull_up=False)  # pin físico 11

print("Leyendo GPIO17. Ctrl+C para salir.")
while True:
    print("valor:", pir.value)
    sleep(0.5)
