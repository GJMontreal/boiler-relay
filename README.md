The philosophy guiding this project and its documentation is straightforward: get it working then make improvements as needed. Perfection is the enemy of progress.

# Plumbing

Overall the heating system is quite simple. A boiler is connected via a manifold with zone valves to a series of radiators. When a zone calls for heat, first the zone valve opens, and when that is complete, the boiler and pump are then turned on.

![plumbing overview](./img/plumbing_overview.jpeg)
Manifold with zone valves
![manifold](./img/manifold.jpeg)

# Electronics
A beaglebone SBC running debian hosts all the software pieces as well as interfacing via GPIO to a relay board. The relays control the zone valves as well as the boiler

![electronics overview](./img/electronics_overview.jpeg)
Beaglebone and relay board
![electronics](img/electronics.jpeg)
# Software
This script contains the logic for zone and boiler control. Sensor data is sent to an MQTT broker (mosquitto in this case). A simple bridge written in python publishes these values to redis. The homebridge plugin reads and writes respective values to redis. Another script, again written in python, toggles the physical gpios based on these values.
The bits circled in red are the ones I've written. The UI is implemented as an ![Homebridge plugin](https://github.com/GJMontreal/heating) 

![software overview](img/software_overview.jpeg)
![software](img/ui.jpeg)

