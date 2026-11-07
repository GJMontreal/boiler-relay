from src.output_thread import PIDThread

class Zone():
    def __init__(self, zone_config, redis_config):
        self.name = zone_config.name
        self.input_path = zone_config.sensor_path
        self.output_path = zone_config.control_path
        self.pid_thread = ( PIDThread(self.input_path,
                                      self.output_path,
                                    zone_config.pid_interval,
                                    self)) #not super keen about passing in self

        self.control_value = 0
        self.target_temperature = 0
        self.current_temperature = 0
        self.last_sample_time = None

    def start(self):
        self.pid_thread.start()

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

