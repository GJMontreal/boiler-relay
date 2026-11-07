# Copyright 2021 Geoffrey Jones
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from threading import Thread
import json
import time
import redis 
# import Adafruit_BBIO.GPIO as GPIO
from src.gpio import GPIO
from enum import Enum
import csv
from simple_pid import PID
# import datetime
import os
# from src.zone import Zone


TIME_CONSTANT = 60 #is this in minutes?
LOG_PATH = "/tmp/ramdisk/boiler-relay" #our log path should be set elsewhere
ACTIVE_LOW = True

# these should be on a per zone basis
Kp = 1
Ki = 0.01
Kd = 0.5

class BoilerThread(Thread):
    def __init__(self,zones):
        self.zones = zones
        self.interval = 5
        self.output_gpio = 'P8_18'
        self.config_gpio(self.output_gpio)
        super().__init__()

    def config_gpio(self, gpio):
        print(f'configuring GPIO: {gpio} as Output')
        GPIO.setup(gpio, GPIO.OUT)
        output = GPIO.LOW
        if ACTIVE_LOW:
            output = GPIO.HIGH
        GPIO.output(gpio, output)
        GPIO.cleanup()

# we should be able to read either a gpio or directly from say redis
    def run(self):
        while True:
            #read each of the inputs
            combined_state = 0
            for zone in self.zones:
                print(f'reading {zone.name} {zone.input_gpio} {GPIO.input(zone.input_gpio)}')
                combined_state = combined_state or GPIO.input(zone.input_gpio)

            print(f'boiler {combined_state}')
            output_state = combined_state
            if ACTIVE_LOW:
                output_state = combined_state * -1 + 1
            GPIO.output(self.output_gpio, output_state)

            time.sleep(self.interval)



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

    def __init__(self, input_path, output_path, interval, zone):
        self.zone = zone
        print(f'init PID thread for: {zone.name}')
        self.input_path = input_path
        self.output_path = output_path
        self.pid_interval = interval
        self.last_sample_time = ""

# the redis config needs to be passed in
        self.r = redis.Redis(host='localhost',port=6379,db=0)

        self.pid = self.init_pid()
        self.control_value = float(0.0)
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
        message = self.r.get(f'{self.input_path}/current_temperature')
        if message:
            data = json.loads(message.decode('utf-8'))
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
                self.last_sample_time = data['time']

            self.current_temperature = current_temperature
            control_value = self.pid(self.current_temperature)
            
            message = self.r.get(f'{self.input_path}/target_temperature')
            if message:
                data = json.loads(message.decode('utf-8'))
                self.setpoint = float(data['value'])
            self.pid.setpoint = self.setpoint

            self.r.set(self.output_path, control_value)
            
            print(f'PID {self.zone.name} {control_value:.3f} {self.current_temperature} {self.setpoint}')

            time.sleep(self.pid_interval)



