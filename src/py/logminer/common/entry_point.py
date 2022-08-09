#! /usr/bin/env python3
""""
Entry point for the Drain3 services
"""
from builtins import object
from builtins import str
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import signal
import socket
import time

from absl import flags
import yaml

FLAGS = flags.FLAGS
flags.DEFINE_boolean('debug', False, 'Enable debug level logs')
flags.DEFINE_string('setting_file', '/logminer/config/settings.yaml',
                    'absolute path to the yaml settings file')
flags.DEFINE_string('wait_for_conn', '',
                    'Wait for <IP:port> pair to be up before proceeding')
flags.DEFINE_boolean('log_to_console', 'True',
                     'output logs to stdout')

logger = logging.getLogger()


class EntryPoint(object):
    """
    Base Entry point for all executables, does the common initialization
    and provides signal handling for graceful shutdown
    """
    settings_dict = {}

    def __init__(self):
        """
        Initialize
        """
        self.name = self.__class__.__name__

    def init_logging(self):
        """
        Initialize the logger
        """
        logger.info("Logging level debug " + str(FLAGS.debug))
        if FLAGS.debug:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

        if not FLAGS.log_to_console:
            logging.log_dir = "/var/log/drain3"
            if not os.path.exists(logging.log_dir):
                os.makedirs(logging.log_dir)

            log_path = '{}/{}.log'.format(logging.log_dir, self.name)

            file_handler = TimedRotatingFileHandler(log_path,
                                                    when='D',
                                                    backupCount=30)
            log_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - '
                '%(levelname)s - %(message)s')
            file_handler.setFormatter(log_formatter)
            logger.handlers = []
            logger.addHandler(file_handler)
            logger.info('Logging Initialized: %s', log_path)

    def signal_handler(self, signum, frame) -> None:
        """
        Handle the signal
        :param signum:
        :param frame:
        :return:
        """
        _ = frame
        logger.info('EntryPoint: %s.signal_handler: called %d',
                    self.name, signum)
        logger.info('EntryPoint: %s.signal_handler: starting graceful shutdown',
                    self.name)
        logger.info('EntryPoint: %s.signal_handler, shutdown complete')

    def register_signal_handlers(self) -> None:
        """
        Register the signal handlers to catch keyboard interrupts
        :return:
        """
        signal.signal(signal.SIGALRM, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    @staticmethod
    def wait_for_conn_up(ip_addr, port, timeout_secs=120):
        """Check if connection is being accepted on given <ip_addr:port> pair"""
        logger.info("Waiting for %s:%s to be up", ip_addr, port)
        while timeout_secs > 0:
            sock = socket.socket()
            sock.settimeout(5)
            try:
                sock.connect((ip_addr, port))
                sock.close()
                logger.info("Successfully connected to %s:%s", ip_addr, port)
                return
            # pylint: disable-msg=W0703  # Catching too general exception
            except Exception as e:
                # Try connecting again
                logger.info("Failed to connect to %s:%s due to %s. Retrying",
                            ip_addr, port, e)
                timeout_secs -= 10
                time.sleep(10)

        # If we reached here, we were unable to connect
        assert False, "Unable to connect to %s:%s" % (ip_addr, port)

    @staticmethod
    def wait_for_all_conns_up() -> None:
        """Check if connections are being accepted on all <ip_addr:port>"""
        if not FLAGS.wait_for_conn:
            return

        ip_port_pairs = FLAGS.wait_for_conn.split(',')
        for pair in ip_port_pairs:
            ip_addr, port = pair.split(':')
            port = int(port)
            EntryPoint.wait_for_conn_up(ip_addr, port)

    @staticmethod
    def wait_for_service_ready() -> None:
        """Wait for several checks to pass before starting service.

        Override this method if you want to add more checks for your particular
        service.
        """
        # Wait for connections to be up
        EntryPoint.wait_for_all_conns_up()

    def run(self, argv) -> None:
        """
        Create the drain3_consumers and start all the consumers
        :param argv:
        :return:
        """
        del argv
        logger.info('Loading settings from %s', FLAGS.setting_file)
        EntryPoint.load_yaml_settings(FLAGS.setting_file)

        self.init_logging()
        EntryPoint.wait_for_service_ready()

        logger.info('Registering signal handlers')
        self.register_signal_handlers()

        # logger.info('Initializing Telemetry')
        # Telemetry.initialize()

        logger.info('Calling custom initializer')
        self.start()

    def start(self) -> None:
        """
        Override this method to do any custom initialization and
        start the main loop of app
        """
        raise NotImplementedError('EntryPoint.start must be implemented')

    @staticmethod
    def load_yaml_settings(settings_file):
        stream = open(settings_file, 'r')
        EntryPoint.settings_dict = yaml.load(stream)
