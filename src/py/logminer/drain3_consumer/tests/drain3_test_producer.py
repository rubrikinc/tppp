"""
Drain3TestProducer
"""

from builtins import object
from builtins import range
import json
import logging
import os
import random
import sys
import time

from absl import app
import kafka
from pyformance import meter_calls
from pyformance import time_calls

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from common.entry_point import EntryPoint  # noqa

logger = logging.getLogger()


class Drain3TestProducer(object):
    """
    This is a test class for generating test logs against a local kafka.
    """

    def __init__(self, producer_settings):
        """
        Initialize the kafka logs producer.
        :param producer_settings: settings for Topic name and kafka brokers
        """
        self.producer_settings = producer_settings
        self.producer = kafka.KafkaProducer(
            bootstrap_servers=producer_settings['kafka_brokers'])

    @meter_calls
    @time_calls
    def send_message(self, msg: str, partition_id: int) -> None:
        """
        Send the message to the kafka.
        :param msg:
        :param partition_id
        """
        self.producer.send(self.producer_settings['topic'],
                           value=json.dumps(msg).encode('utf-8'),
                           partition=partition_id)

    def start_producing(self):
        """
        Starts the single threaded kafka producer.
        :return:
        """
        logger.info(" Inputing logs from a test logs file")
        f = open(os.path.join(os.path.dirname(__file__), "test_logs.json"))
        logs = json.load(f)["logs"]
        while True:
            for node in range(self.producer_settings['num_nodes']):
                for msg in logs:

                    self.send_message(
                        msg,
                        node % self.producer_settings['num_partitions'])
            logger.info('Finished one set of producing logs')


class Drain3ProducerApp(EntryPoint):
    """
    Entry point class for the drain3 producer/consumer
    """

    def __init__(self):
        EntryPoint.__init__(self)

    @staticmethod
    def wait_for_service_ready() -> None:
        # Wait for connections to be up
        EntryPoint.wait_for_service_ready()

        # Wait for topic to exist
        producer_settings = EntryPoint.settings_dict['drain3_test_producer']
        client = kafka.KafkaClient(producer_settings['kafka_brokers'])
        client.ensure_topic_exists(producer_settings['topic'], timeout=120)

    def start(self):
        """
        Initialize the write path and start the consumers
        :return:
        """
        logger.info("Creating the Drain3TestProducer")
        settings = EntryPoint.settings_dict['drain3_test_producer']
        drain3_test_producer = Drain3TestProducer(settings)

        logger.info("Starting to produce logs")
        drain3_test_producer.start_producing()
        logger.info('Done generating all data. Sleeping indefinitely now')
        time.sleep(86400 * 1000)

if __name__ == "__main__":
    app.run(Drain3ProducerApp().run)
