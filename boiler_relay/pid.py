from time import monotonic


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


class PID:
    def __init__(self, kp, ki, kd, integral_cap=1.0, sample_time=0.01, time_fn=monotonic):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral_cap = integral_cap
        self.sample_time = sample_time
        self.time_fn = time_fn
        self.setpoint = 0
        self.reset()

    @property
    def integral(self):
        return self.integral_term

    def reset(self):
        self.integral_term = 0.0
        self.last_time = self.time_fn()
        self.last_output = None
        self.last_input = None

    def __call__(self, measurement):
        now = self.time_fn()
        dt = now - self.last_time if (now - self.last_time) else 1e-16
        if dt < self.sample_time and self.last_output is not None:
            return self.last_output

        error = self.setpoint - measurement
        d_input = measurement - (self.last_input if self.last_input is not None else measurement)

        proportional = self.kp * error
        self.integral_term = clamp(self.integral_term + self.ki * error * dt, 0.0, self.integral_cap)
        derivative = -self.kd * d_input / dt

        output = clamp(proportional + self.integral_term + derivative, 0.0, 1.0)

        self.last_output = output
        self.last_input = measurement
        self.last_time = now
        return output
