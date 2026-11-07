from threading import Thread
from time import sleep
from redis import Redis

from src.gpio import GPIO
from src.heating_cooling_state import HeatingCoolingState


class ZoneValveThread(Thread):
    def __init__(self, sensor_path, output_gpio, active_low, zone):
        self.zone = zone
        self.sensor_path = sensor_path
        self.output_gpio = output_gpio
        self.active_low = active_low
        
        for gpio in self.output_gpio:
            self.config_gpio(gpio)

        self.r = Redis(host='localhost',port=6379,db=0) #the host and port should be in a config
        self.interval = 5
        self.cycle = 0
        self.duration = 10 * 60 / self.interval
        super().__init__()

    def config_gpio(self, gpio):
        print(f'configuring GPIO: {gpio} as Output')
        GPIO.setup(gpio, GPIO.OUT)
        output = GPIO.LOW
        if self.active_low == True:
            output = GPIO.HIGH
        GPIO.output(gpio, output)
        GPIO.cleanup()

    def run(self):
        while True:
            topic = f'{self.sensor_path}/target_heatingcooling_state'
            message = self.r.get(topic)
            if message is None:
                sleep(self.interval)
                continue

            value = int(message.decode('utf-8'))
            target_heatingcooling_state = HeatingCoolingState(value)

            topic = f'{self.sensor_path}/control_value'
            message = self.r.get(topic)
            if message is None:
                sleep(self.interval)
                continue

            control_value = float(message.decode('utf-8'))

            heating_cooling_state = HeatingCoolingState.OFF 
            
            on_time = int(control_value * self.duration)

            if ( target_heatingcooling_state != HeatingCoolingState.OFF 
                    and on_time > 0 and on_time > self.cycle ): 
                
                heating_cooling_state = HeatingCoolingState.HEAT
            
            topic = f'{self.sensor_path}/boost'
            message = self.r.get(topic)
            if message is not None:
                bool_value = json.loads(message)
                if bool_value == True:
                    heating_cooling_state = HeatingCoolingState.HEAT

            #logging should be done to a file not stdout
            #print(f'{self.sensor_path} {self.thermostat.target_temperature} {self.thermostat.current_temperature} {self.cycle} {on_time} {heating_cooling_state.value} {control_value}')
            output = heating_cooling_state.value
            if self.active_low:
                output = output * -1 + 1

            for gpio in self.output_gpio:
                GPIO.output(gpio, output)
            
            print(f'zone_valve {self.zone.name} {self.output_gpio} {heating_cooling_state}\n')

            topic = f'{self.sensor_path}/heating_cooling_state'
            self.r.set(topic,heating_cooling_state.value)
            self.r.publish(topic,heating_cooling_state.value)

            self.cycle += 1
            if self.cycle > self.duration - 1:
                self.cycle = 0

            sleep(self.interval)
