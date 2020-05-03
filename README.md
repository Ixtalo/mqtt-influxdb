# mqtt-influxdb

Store MQTT messages to InfluxDB, .i.e., a MQTT-InfluxDB-Bridge.


## Requirements
* Python 3.7+
* Python virtualenv
* MQTT server, e.g., Mosquitto
* InfluxDB server


## Getting Started
1. Set up MQTT and InfluxDB servers.
    * For testing purposes you can use the Docker-Compose script: `cd ./scripts/docker-mqtt-influxdb/ && docker-compose up -d`.
2. Create Python virtualenv: `python3 -m virtualenv --python=python3 --system-site-packages env`
    * Use Python3
    * `--system-site-packages` Give the virtual environment access to the global site-packages.
    * Create virtualenv in subfolder `./venv/`
3. Activate virtualenv: `source venv/bin/activate`
4. Run `python3 mqtt-influxdb.py`
5. (Install as systemd-service, see `./scripts/systemd/`)

