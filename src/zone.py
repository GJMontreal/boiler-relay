import csv
import os

from src.actuator import create_output
from src.output_thread import LOG_PATH, PIDThread
from src.zone_valve_thread import ZoneValveThread

class Zone():
    def __init__(self, zone_config, redis_config, mqtt_config):
        self.name = zone_config.name
        self.input_path = zone_config.sensor_path
        self.output_path = zone_config.control_path
        self.pid_thread = ( PIDThread(self.input_path,
                                      self.output_path,
                                    zone_config.pid_interval,
                                    self,
                                    redis_config)) #not super keen about passing in self

        self.zone_valve_thread = ZoneValveThread(self.input_path,
                                                 self,
                                                 redis_config)

        self.actuators = []
        for output in zone_config.outputs:
            output = {"active_low": zone_config.active_low, **output}
            actuator = create_output(output, self.input_path, redis_config, mqtt_config)
            if actuator is not None:
                self.actuators.append(actuator)

        self.control_value = 0
        self.target_temperature = 0
        self.current_temperature = 0
        self.last_sample_time = None

    def start(self):
        self.pid_thread.start()
        self.zone_valve_thread.start()
        for actuator in self.actuators:
            actuator.start()

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

