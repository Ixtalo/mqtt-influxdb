#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=line-too-long,invalid-name
"""mqtt-influxdb - Store MQTT messages to InfluxDB.

Subscribes to a MQTT server and stores incoming messages to InfluxDB.

Usage:
  mqtt-influxdb.py [-v] [--mqtt-host=host] [--mqtt-port=port] [--mqtt-user=username] [--mqtt-pass=password]
  mqtt-influxdb.py -h | --help
  mqtt-influxdb.py --version

Arguments:
  None.

Options:
  --mqtt-host=host  Hostname of the MQTT-server [default: localhost]
  --mqtt-port=port  Port of the MQTT-server (broker) [default: 1883]
  --mqtt-user=str   MQTT authentication username
  --mqtt-pass=str   MQTT authentication password
  -v --verbose      More output.
  -h --help         Show this screen.
  --version         Show version.
"""
import logging
import os
import signal
import sys
from json import loads, dumps
from time import ctime, time

import paho.mqtt.client as mqtt   # https://pypi.org/project/paho-mqtt/
from docopt import docopt
from influxdb import InfluxDBClient

__author__ = "Alexander Streicher"
__email__ = "ixtalo@gmail.com"
__copyright__ = "Copyright (C) 2018 Alexander Streicher"
__license__ = "GPL"
__version__ = "1.0"
__date__ = "2020-05-02"
__updated__ = '2020-05-02'
__status__ = "Production"

MQTT_SUBSCRIBE_TOPICS = ('#',)  # list of MQTT subscription topics
DB_NAME = 'mqtt'  # database name

######################################################
######################################################
######################################################

MYNAME = 'mqtt-influxdb'
DEBUG = 1
TESTRUN = 0
PROFILE = 0

EXITCODE_OK = 0
EXITCODE_MQTT_CON = 1
EXITCODE_MQTT_EXCEPTION = 2
EXITCODE_MQTT_DISCONNECT = 3

## global fields/variables
logger = logging.getLogger(MYNAME)
mqtt_client = mqtt.Client()
db_client = None


def signal_handler_sigint(sig, frame):
    """
    CTRL+C handling
    http://stackoverflow.com/questions/1112343/how-do-i-capture-sigint-in-python
    """
    logger.debug("SIGNAL: %s, %s", sig, frame)
    logger.warning('Ctrl+C pressed or SIGINT signal received. Stopping!')
    print('Ctrl+C pressed or SIGINT signal received. Stopping!')
    cleanup()
    sys.exit(EXITCODE_OK)


# def signal_handler_sigusr1(signal, frame):
#    logger.warn('SIGUSR1 sent! Persisting...')

def cleanup():
    """
    Controlled clean-up.
    """
    ## MQTT disconnect
    errno = mqtt_client.disconnect()
    if errno != mqtt.MQTT_ERR_SUCCESS:
        logger.warning("Problem disconnecting from MQTT server: %s", mqtt.error_string(errno))
        sys.exit(EXITCODE_MQTT_DISCONNECT)


# noinspection PyUnusedLocal
def on_connect(client, userdata, flags, rc):
    """
    MQTT event for establishing a connection.
    """
    # pylint: disable=unused-argument
    logger.info("MQTT: Connected with result code %d", rc)
    if rc == mqtt.MQTT_ERR_SUCCESS:
        ## Subscribing here in on_connect() means that if we lose the
        ## connection and reconnect then subscriptions will be renewed.
        subscribe(client)
    else:  # not mqtt.MQTT_ERR_SUCCESS
        logger.warning("MQTT: Connection error: %s", mqtt.error_string(rc))


# noinspection PyUnusedLocal
def on_disconnect(client, userdata, rc):
    """
    MQTT event when disconnected.
    """
    # pylint: disable=unused-argument
    if rc == mqtt.MQTT_ERR_SUCCESS:
        logger.debug('MQTT: disconnect successful.')
    else:
        logger.warning("MQTT: disconnected! %s (%d)", mqtt.error_string(rc), rc)
        if rc == mqtt.MQTT_ERR_NOMEM:
            logger.warning('MQTT: MQTT_ERR_NOMEM - is another instance running?!')
            try:
                errno = client.reconnect()
                if errno == mqtt.MQTT_ERR_SUCCESS:
                    logger.warning('Reconnect after disconnect OK.')
                else:
                    logger.error("Problem reconnecting to MQTT server: %s", mqtt.error_string(errno))
            except Exception as ex:
                logger.error("Exception when reconnecting to MQTT server: %s", ex)


### https://stackoverflow.com/questions/22199741/identifying-the-data-type-of-an-input
from ast import literal_eval
def get_type(input_data):
    try:
        return type(literal_eval(input_data))
    except (ValueError, SyntaxError):
        # A string, so return str
        return str

# noinspection PyUnusedLocal
def on_message(client, userdata, msg):
    """
    MQTT event when a message arrives.
    """
    # pylint: disable=unused-argument
    payload = msg.payload
    if not payload:
        logger.debug("Empty message, ignoring...")
        return

    ## convert binary payload
    try:
        payload = payload.decode('utf8')
    except Exception as ex:
        logger.warning("Payload decoding problem: %s", ex)

    payload_type = get_type(payload)
    payload_type_name = payload_type.__name__
    logger.debug("payload_type: %s", payload_type_name)

    if payload_type is int or payload_type is float:
        payload_type_name = 'float'
        payload_value = float(payload)
    elif payload_type is bool:
        payload_value = bool(payload)
    elif payload_type is dict or payload_type is list:
        try:
            ## try to convert to JSON then back to string
            payload_value = dumps(loads(payload, parse_float=float))
            payload_type_name = 'json'
        except Exception as ex:
            ## ignore exception
            logger.debug("(ignorable) payload JSON parsing problem: %s", ex)
            payload_value = str(payload)
            payload_type_name = 'str'
    else:
        payload_value = str(payload)
        payload_type_name = 'str'

    logger.debug("parsed payload (type %s): %s", payload_type_name, payload_value)

    ## construct container
    db_data = [{
        "measurement": "messages",
        "tags": {
            "topic": msg.topic
        },
        "fields": {
            "payload_%s" % payload_type_name: payload_value
            }
        }
    ]

    ## store in database
    try:
        result = db_client.write_points(db_data)
        if not result:
            logger.error("DB insert error!")
    except Exception as ex:
        logger.error("DB insert error exception: %s", ex)


# noinspection PyUnusedLocal
def on_subscribe(client, userdata, mid, granted_qos):
    """
    MQTT event when subscribed to a topic.
    """
    # pylint: disable=unused-argument
    logger.info("MQTT: subscribed. (granted QOS=%s)", str(granted_qos))


# noinspection PyUnusedLocal
def on_unsubscribe(client, userdata, mid):
    """
    MQTT event when unsubscribed to a topic.
    """
    # pylint: disable=unused-argument
    logger.warning('MQTT: Unsubscribed!')
    subscribe(client)


# noinspection PyUnusedLocal
def on_log(client, userdata, level, buf):
    """
    Override for MQTT logging.
    """
    # pylint: disable=unused-argument
    logger.debug("%s: %s", level, buf)


def subscribe(client):
    """
    Subscribe to MQTT.
    """
    for topic in MQTT_SUBSCRIBE_TOPICS:
        res, _ = client.subscribe(topic)
        if res == mqtt.MQTT_ERR_SUCCESS:
            logger.debug("MQTT: subscribed to '%s'", topic)
        else:
            logger.warning("MQTT: Could not subscribe to topic '%s'. Result:%s", topic, mqtt.error_string(res))


def _setup_logging(verbose=False):
    """
    set up logging
    :param verbose: more output if True
    """
    global logger
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(
        fmt=logging.Formatter('%(asctime)s - %(levelname)-8s - %(funcName)s:%(lineno)d - %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
    )
    logger.addHandler(console_handler)  # without handler setLevel is not working!
    logger.setLevel(logging.INFO)  # default log level
    if verbose:
        logger.setLevel(logging.DEBUG)
    if DEBUG:
        ## DEBUG overrides
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)


def _log_startup_info():
    ## store the current logging level for later restore
    actual_loglevel = logger.getEffectiveLevel()
    logger.setLevel(logging.INFO)
    logger.info("NEW RUN, version:%s (%s), log-level:%s, cwd:%s, euid:%d, egid:%d, pid:%d",
                __version__,
                __updated__,
                logging.getLevelName(actual_loglevel),
                os.getcwd(),
                os.geteuid(),
                os.getegid(),
                os.getpid()
                )
    logger.info("MQTT library: %s", mqtt)
    ## restore log level
    logger.setLevel(actual_loglevel)


def _setup_mqtt(mqtt_host, mqtt_port, mqtt_user=None, mqtt_pass=None):
    ## set up MQTT
    logger.debug("Initializing MQTT connection...")
    global mqtt_client
    mqtt_client = mqtt.Client(client_id="%s(%s)" % (MYNAME, __version__), clean_session=False)
    # ##mqtt_client.subscribe(MQTT_SUBSCRIBE_TOPIC)  # done in on_connect
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_subscribe = on_subscribe
    mqtt_client.on_unsubscribe = on_unsubscribe
    mqtt_client.on_message = on_message
    if mqtt_user is not None:
        mqtt_client.username_pw_set(mqtt_user, mqtt_pass)
    if DEBUG:
        ## in DEBUG mode attach our logging facility
        mqtt_client.on_log = on_log
    try:
        errno = mqtt_client.connect(mqtt_host, mqtt_port)
        if errno == mqtt.MQTT_ERR_SUCCESS:
            # noinspection PyProtectedMember
            # pylint: disable=protected-access
            logger.info("MQTT: connected to %s:%d as '%s'", mqtt_host, mqtt_port, mqtt_client._client_id)
        else:
            logger.error("Problem connecting to MQTT server: %s", mqtt.error_string(errno))
            return EXITCODE_MQTT_CON
    except Exception as ex:
        logger.error("Exception when connecting to MQTT server %s: %s", mqtt_host, ex)
        return EXITCODE_MQTT_EXCEPTION
    return 0


def _setup_database_connection():
    global db_client
    ## https://influxdb-python.readthedocs.io/en/latest/api-documentation.html#influxdbclient
    db_client = InfluxDBClient(host='localhost', port=8086, database=DB_NAME)
    try:
        db_client.create_database(DB_NAME)
    except Exception as ex:
        logger.warning(ex)


def _setup_signalling():
    """
    Setup signalling for CTRL+C
    ## https://en.wikipedia.org/wiki/Unix_signal
    """
    signal.signal(signal.SIGINT, signal_handler_sigint)
    print('Start time: %s' % ctime())
    print("Press Ctrl+C to quit (PID:%d)" % os.getpid())


def main():
    """
    Program's main entry point.
    :return: exit code
    """
    arguments = docopt(__doc__, version="mqtt-influxdb v%s" % __version__)
    verbose = arguments['--verbose']
    mqtt_host = arguments['--mqtt-host']
    mqtt_port = int(arguments['--mqtt-port'])
    mqtt_user = arguments['--mqtt-user']
    mqtt_pass = arguments['--mqtt-pass']

    ## logging
    _setup_logging(verbose)
    logger.debug("Command line arguments: %s", arguments)
    _log_startup_info()

    ## MQTT connection
    result = _setup_mqtt(mqtt_host, mqtt_port, mqtt_user, mqtt_pass)
    if result != 0:
        return result  # this calls sys.exit(result)

    ## Database
    _setup_database_connection()

    ## CTRL+C handling
    _setup_signalling()

    ## main loop
    # Blocking call that processes network traffic, dispatches callbacks and handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a manual interface.
    mqtt_client.loop_forever(retry_first_connection=False)

    return EXITCODE_OK


if __name__ == "__main__":
    if DEBUG:
        print("---------------- DEBUG MODE -----------------")
        if "--verbose" not in sys.argv:
            sys.argv.append("--verbose")
        # if "--dry-run" not in sys.argv: sys.argv.append("--dry-run")
    if TESTRUN:
        print("---------------- TEST RUN -----------------")
        import doctest
        doctest.testmod()
    if PROFILE:
        print("---------------- PROFILING -----------------")
        import cProfile
        import pstats
        profile_filename = 'profile.txt'
        cProfile.run('main()', profile_filename)
        statsfile = open("profile_stats.txt", "wb")
        p = pstats.Stats(profile_filename, stream=statsfile)
        stats = p.strip_dirs().sort_stats('cumulative')
        stats.print_stats()
        statsfile.close()
        sys.exit(0)
    sys.exit(main())
