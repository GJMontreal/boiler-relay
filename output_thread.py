from threading import Thread
import json
import time
import redis 
import Adafruit_BBIO.GPIO as GPIO
from enum import Enum
import csv
from simple_pid import PID
import datetime
import os

TIME_CONSTANT = 60
LOG_PATH = "/tmp/ramdisk/boiler-relay"

Kp = 1
Ki = 0.01
Kd = 0.5

class BoilerThread(Thread):
    def __init__(self,zones):
        self.zones = zones
        self.interval = 5
        self.output_gpio = 'P8_11'
        self.config_gpio(self.output_gpio)
        super().__init__()

    def config_gpio(self, gpio):
        print(f'configuring GPIO: {gpio} as Output')
        GPIO.setup(gpio, GPIO.OUT)
        GPIO.cleanup()

    def run(self):
        while True:
            #read each of the inputs
            combined_state = 0
            for zone in self.zones:
                print(f'reading {zone.input_gpio} {GPIO.input(zone.input_gpio)}')
                combined_state = combined_state or GPIO.input(zone.input_gpio)

            print(f'boiler {combined_state}')
            GPIO.output(self.output_gpio, combined_state)

            time.sleep(self.interval)


#optionally, our thermostat will create a log thread
class Zone():
    def __init__(self, zone_config):
        self.name = zone_config.name
        self.sensor_path = zone_config.sensor_path

        self.pid_thread = ( PIDThread(zone_config.sensor_path,
                                    zone_config.pid_interval,
                                    self)) #not super keen about passing in self
        self.zone_valve_thread = ( ZoneValveThread(zone_config.sensor_path,
                                            zone_config.output_gpio,
                                            self))

        self.logging_thread = ZoneLoggingThread(self)

        self.input_gpio = zone_config.input_gpio
        self.config_gpio(self.input_gpio)
        
        self.control_value = 0
        self.target_temperature = 0
        self.current_temperature = 0
        self.last_sample_time = None

    def start(self):
        self.pid_thread.start()
        self.zone_valve_thread.start()
        self.logging_thread.start()

    def config_gpio(self, gpio):
        print(f'configuring GPIO: {gpio} as Input')
        GPIO.setup(gpio, GPIO.IN)

    def write_row(self):
        p, i, d = self.pid_thread.pid.components

        #format our numbers
        current_temperature = '{:.1f}'.format(self.current_temperature)
        target_temperature = '{:.1f}'.format(self.target_temperature)
        control_value = '{:.0f}'.format(self.control_value * self.zone_valve_thread.duration)


        p_formatted = '{:.6f}'.format(p)
        i_formatted = '{:.6f}'.format(i)
        d_formatted = '{:.6f}'.format(d)
        
        row = ([ self.last_sample_time,
                current_temperature,
                target_temperature,
                control_value,
                self.zone_valve_thread.cycle,
                p_formatted,
                i_formatted,
                d_formatted])
                
        self.write_row_to_csv(row)

    def write_row_to_csv(self,row):
        file_name = os.path.split(self.name)[-1]  
        file_path = f'{LOG_PATH}/{file_name}_pid.csv' 
        with open(file_path,'a', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',',quoting=csv.QUOTE_NONE)
            writer.writerow(row)


class ZoneLoggingThread(Thread):
    def __init__(self,zone):
        self.zone = zone
        self.interval = 10
        super().__init__()

    def run(self):
        while True:
            if self.zone.last_sample_time:
                self.zone.write_row()

            time.sleep(self.interval)

#this controls zone valve
class ZoneValveThread(Thread):
    def __init__(self, sensor_path, output_gpio, zone):
        self.zone = zone
        self.sensor_path = sensor_path
        self.output_gpio = output_gpio
        self.config_gpio(self.output_gpio)
        self.r = redis.Redis(host='localhost',port=6379,db=0) #the host and port should be in a config
        self.interval = 5
        self.cycle = 0
        self.duration = 10 * 60 / self.interval
        super().__init__()

    def config_gpio(self, gpio):
        print(f'configuring GPIO: {gpio} as Output')
        GPIO.setup(gpio, GPIO.OUT)
        GPIO.cleanup()

    def run(self):
        while True:
            topic = f'{self.sensor_path}/target_heatingcooling_state'
            message = self.r.get(topic)
            if message == None:
                time.sleep(self.interval)
                continue

            value = int(message.decode('utf-8'))
            target_heatingcooling_state = HeatingCoolingState(value)

            topic = f'{self.sensor_path}/control_value'
            message = self.r.get(topic)
            if message == None:
                time.sleep(self.interval)
                continue

            control_value = float(message.decode('utf-8'))

            heating_cooling_state = HeatingCoolingState.OFF 
            
            on_time = int(control_value * self.duration)

            if ( target_heatingcooling_state != HeatingCoolingState.OFF 
                    and on_time > 0 and on_time > self.cycle ): 
                
                heating_cooling_state = HeatingCoolingState.HEAT
            
            #logging should be done to a file not stdout
            #print(f'{self.sensor_path} {self.thermostat.target_temperature} {self.thermostat.current_temperature} {self.cycle} {on_time} {heating_cooling_state.value} {control_value}')
            GPIO.output(self.output_gpio,heating_cooling_state.value)
            print(f'zone_valve {heating_cooling_state}')
            topic = f'{self.sensor_path}/heating_cooling_state'
            self.r.set(topic,heating_cooling_state.value)
            self.r.publish(topic,heating_cooling_state.value)

            self.cycle += 1
            if self.cycle > self.duration - 1:
                self.cycle = 0

            time.sleep(self.interval)

            

            

class HeatingCoolingState(Enum):
    OFF = 0
    HEAT = 1
    COOL = 2

class PIDThread(Thread):
    last_message = ""
    current_temperature = 0
    setpoint = 0
    target_heating_cooling_state = HeatingCoolingState.OFF
    heating_cooling_state = HeatingCoolingState.OFF

#we'll need to add a way to log the output, an option and path
#while developing some kind of algorithm, we can gather data

    def __init__(self, sensor_path, interval, zone):
        self.zone = zone
        print(f'init PID thread for: {zone.name}')
        self.sensor_path = sensor_path
        self.pid_interval = interval

        self.r = redis.Redis(host='localhost',port=6379,db=0)

        self.pid = self.init_pid()
        self.control_value = 0
        super().__init__()

    def init_pid(self):
        current_temperature = 0
        data  = self.get_current_temperature()
        if data:
          current_temperature = float(data['value'])
        
        pid = PID(Kp, Ki, Kd,setpoint=current_temperature,sample_time = 1, output_limits=[0,1])
        return pid

    def get_current_temperature(self):
        value = 0.0
        data = None
        message = self.r.get(f'{self.sensor_path}/current_temperature')
        if message:
            data = json.loads(message.decode('utf-8'))
            #value = float(data['value'])
            #we should return the time stamp as well

        return data
    
    #move to zone
    def write_row(self):
        p, i, d = self.pid.components

        #format our numbers
        current_temperature = '{:.1f}'.format(self.current_temperature)
        target = '{:.1f}'.format(self.setpoint)
        control_value = '{:.3f}'.format(self.control_value)

        p_formatted = '{:.6f}'.format(p)
        i_formatted = '{:.6f}'.format(i)
        d_formatted = '{:.6f}'.format(d)
        
        row = ([ self.zone.last_sample_time,
                current_temperature,
                target,
                control_value,
                p_formatted,
                i_formatted,
                d_formatted])
                
        self.write_row_to_csv(row)

    def write_row_to_csv(self,row):
        file_name = os.path.split(self.sensor_path)[-1]  
        file_path = f'{LOG_PATH}/{file_name}_pid.csv' 
        with open(file_path,'a', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',',quoting=csv.QUOTE_NONE)
            writer.writerow(row)

    def run(self):
        print(f'running PID thread for: {self.zone.name}')
        
        while True:
            current_temperature = 0
            
            data = self.get_current_temperature()
            if data != None:
                current_temperature = float(data['value'])
                self.zone.last_sample_time = data['time']

            self.current_temperature = current_temperature
            control_value = self.pid(self.current_temperature)
            
            message = self.r.get(f'{self.sensor_path}/target_temperature')
            if message:
                data = json.loads(message.decode('utf-8'))
                self.setpoint = float(data['value'])
            self.pid.setpoint = self.setpoint

            # print(f'{self.sensor_path} {self.control_value} {self.current_temperature} {self.setpoint}')
            self.zone.current_temperature = self.current_temperature
            self.zone.target_temperature = self.setpoint
            self.zone.control_value = control_value

            topic = f'{self.sensor_path}/control_value'
            self.r.set(topic, control_value)
            self.r.publish(topic, control_value)
            
            # if self.zone.last_sample_time != None:
            #     self.write_row()

            time.sleep(self.pid_interval)



