from json import loads
from threading import Thread
from time import sleep
from redis import Redis

from src.heating_cooling_state import HeatingCoolingState


class ZoneValveThread(Thread):
    def __init__(self, sensor_path, zone, redis_config):
        self.zone = zone
        self.sensor_path = sensor_path
        self.r = Redis(host=redis_config.host, port=redis_config.port, db=0)
        self.interval = 5
        self.cycle = 0
        self.duration = 10 * 60 / self.interval
        super().__init__()

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
                bool_value = loads(message)
                if bool_value == True:
                    heating_cooling_state = HeatingCoolingState.HEAT

            #logging should be done to a file not stdout
            #print(f'{self.sensor_path} {self.thermostat.target_temperature} {self.thermostat.current_temperature} {self.cycle} {on_time} {heating_cooling_state.value} {control_value}')
            print(f'zone_valve {self.zone.name} {heating_cooling_state}\n')

            topic = f'{self.sensor_path}/heating_cooling_state'
            self.r.set(topic,heating_cooling_state.value)
            self.r.publish(topic,heating_cooling_state.value)

            self.cycle += 1
            if self.cycle > self.duration - 1:
                self.cycle = 0

            sleep(self.interval)
