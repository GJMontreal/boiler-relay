import json
import Adafruit_BBIO.GPIO as GPIO
import argparse
from pprint import pprint
from output_thread import Zone, BoilerThread

class BoilerConfig:
    def __init__(self,output_gpio, zones):
        self.output_gpio = output_gpio
        self.zones = zones

class ZoneConfig:
    def __init__(self,dict):
        self.sensor_path = dict['sensor_path']
        self.input_gpio = dict['input_gpio']
        self.output_gpio = dict['output_gpio']
        self.name = dict['name']
        self.pid_interval = 5 #seconds
        self.control_interval = 10 #minutes

class ThermostatConfig:
    def __init__(self,path,gpio):
        self.path = path #sensor data
        self.gpio = gpio #like P8_10
        self.pid_interval = 5 #seconds
        self.control_duration = 10 #minutes

#we need a mapping between gpios and sensors
def setup_outputs(outputs):
    #we could be using map for this
    for output in outputs:
        print(f'configuring GPIO: {output.gpio}')
        GPIO.setup(output.gpio, GPIO.OUT)
        GPIO.output(output.gpio, GPIO.HIGH)

def create_thermostats(configs):
    thermostats = []
    for config in configs:
        print(f'creating thermostat for: {config.path}')
        thermostats.append(Thermostat(config))
    return thermostats

def create_zones(file_path):
    print(f'creating zones from config {file_path}')
    zones = []
    with open(file_path) as json_file:
        data = json.load(json_file)
        for entry in data['zones']:
            zone = Zone(ZoneConfig(entry))
            zones.append(zone)
    return zones

def read_config(file_path):
    print(f'reading config {file_path}')
    zones = []
    with open(file_path) as json_file:
        data = json.load(json_file)
        for entry in data['zones']:
            zone = Zone(ZoneConfig(entry))
            zones.append(zone)
    return zones

def parse_arguments():
    parser = argparse.ArgumentParser(description='Get config file path')
    parser.add_argument('--config', '-c', help = 'config file', default='config.json')
    args = parser.parse_args()
    return args.config

def pprint_outputs(outputs):
    for output in outputs:
        pprint(vars(output))


if __name__ == "__main__":
    config_path = parse_arguments()
    
    zones = create_zones(config_path)
    for zone in zones:
        zone.start()
    
    boiler = BoilerThread(zones)
    boiler.start()

