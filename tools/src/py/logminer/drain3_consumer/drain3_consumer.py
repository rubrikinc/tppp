"""
Consumer class for running drain3 on logs
"""
from __future__ import absolute_import
from __future__ import division

from builtins import object
from builtins import range
from builtins import str
import json
import logging
import os
from os.path import dirname
from os.path import join
import random
import socket
import time
import traceback

from confluent_kafka import Consumer
from confluent_kafka import KafkaError
from confluent_kafka import KafkaException
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence

from template_miner_intervalpersistence import TemplateMinerWithIntervalPersistence  # NOQA

logger = logging.getLogger()
REDIS_TTL = 900
BATCH_SIZE = 1000


class Drain3Consumer(object):
    """ Drain3 consumer for log clustering.
        :param :settings_dict dict with kafka topic,broker servers and resettime
        :param persistence: persistence object to connect to redis
        :param config: drain3 config object
    """
    def __init__(self, settings_dict, persistence=None, config=None):
        settings = settings_dict['drain3_consumer']
        self.servers = settings['kafka_brokers']
        self.consumer_group = settings['group']
        self.topic = settings['topic']
        self.consumer: Consumer = None
        self.running = True
        self.drain3_objects = {}
        self.persistence = persistence
        self.config = config
        self.reset_interval_time = settings.get('reset_interval_time')
        self.batch_size = settings.get('batch_size', BATCH_SIZE)
        self.training_time = settings.get('training_time')
        self.training = True
        self.training_sampling = settings.get('training_sampling', 100)
        self.inference_sampling = settings.get('inference_sampling', 100)
        self.counter = 0
        self.last_reset_time = time.time()
        self.saved_object_path = settings.get('saved_object_path', '/logminer/drain3_obj')

    def add_drain3_object(self, service, version):
        """
        Create drain3 object for a service and add to the drain3 objects dict.
        :param service: Name of the service
        :param Version: Version of the service
        """
        logger.info("Adding drain3 object for %s_%s", service, version)
        if self.persistence is None:
            if not os.path.exists(self.saved_object_path):
                os.makedirs(self.saved_object_path)
            persistence = FilePersistence("%s/%s_%s" % (self.saved_object_path, service, version))
        else:
            persistence = self.persistence
        if self.config is None:
            config = TemplateMinerConfig()
            config.load(join(dirname(__file__), "..", "config", "drain3.ini"))
            logger.info(join(dirname(__file__), "..", "config", "drain3.ini"))
        else:
            config = self.config

        logger.debug("Snapshot time is %s min",
                     str(config.snapshot_interval_minutes))

        template_miner = TemplateMinerWithIntervalPersistence(persistence,
                                                              config)
        self.drain3_objects[service][version] = template_miner

        logger.info("Total drain3 objects %s", str(len(self.drain3_objects)))

    def remove_fields(self, log_message):
        """
        Remove irrelevant fields from log message before inputting to drain3.
        Improves drain3 pattern extraction.
        :param log_message: log message obtained from kafka
        """
        # TODO: move inside a derived logcluster object.
        fields_delete = ['ClusterUuid', 'Uuid', 'Timestamp', 'Hostname',
                         'time', 'EnvVersion', 'Thread', 'Pid', 'JobId',
                         'Version', "Type"]
        for field in fields_delete:
            log_message.pop(field, None)
        return log_message["Payload"]

    def process_log(self, log_message):

        # Implementing sampling
        random_num = random.randint(1, 100)
        if self.training and random_num > self.training_sampling:
            return

        if not self.training and random_num > self.inference_sampling:
            return

        service = log_message['Logger']
        version = log_message['Version']
        log_message = self.remove_fields(log_message)
        #logger.debug("Processing log %s", log_message)
        time_diff_mins = (time.time() - self.last_reset_time) / 60.0
        if self.counter == self.batch_size:
            # Reset drain3 state if reset period reached
            if self.reset_interval_time is not None and \
               time_diff_mins > self.reset_interval_time:
                logger.info("Time since reset:%s minutes. Starting reset",
                            str(time_diff_mins))
                self.reset()
            # Switch to fast matching on training period end
            elif (self.training and
                  self.training_time is not None and
                  time_diff_mins > self.training_time):
                logger.info("Switching to fast matching."
                            "Training time:%s minutes",
                            str(time_diff_mins))
                self.training = False

            self.counter = 0
        if service not in self.drain3_objects:
            self.drain3_objects[service] = {}
        if version not in self.drain3_objects[service]:
            self.add_drain3_object(service, version)

        template_miner = self.drain3_objects[service][version]
        # Training period
        if self.training:
            result = template_miner.add_log_message(json.dumps(log_message))

            """
            Log the resultant cluster if there is any change in the pattern.
            """
            #if result["change_type"] != "none":
                
            #    logger.debug("Cluster modified " + str(json.dumps(result)))
        else:
            """
            Inference period: log message is matched to existing clusters.
            No change in cluster patterns.
            """
            # Returns matched cluster or None if no perfect match found
            result = template_miner.match(json.dumps(log_message))
            if result:
                logger.debug("Log Match found:%s",
                            result.get_template())
        self.counter += 1

    def subscribe_topic_kafka(self):
        retries = 8
        for i in range(retries):

            if self.topic not in self.consumer.list_topics().topics:
                logger.info("Topic not in Kafka yet... Retrying subscribe")
                time.sleep(10)
            else:
                self.consumer.subscribe([self.topic])
                break


    def start_consumer(self):
        conf = {'bootstrap.servers': self.servers,
                'group.id': self.consumer_group,
                'auto.offset.reset': "earliest"}

        self.consumer = Consumer(conf)
        self.subscribe_topic_kafka()
        try:
            while self.running:
                log = self.consumer.poll(timeout=1)
                if log is None:
                    logger.debug("Empty log")
                    continue

                if log.error():
                    logger.error('%s: Failed to process: %s '
                                 'Exception: %s ST: %s',
                                 self.__class__.__name__, log, log.error(),
                                 traceback.format_exc())
                else:
                    try:
                        self.process_log(
                            json.loads(log.value().decode('utf-8')))
                    except Exception as err:
                        logger.error('%s: Failed to process: %s '
                                     'Exception: %s ST: %s',
                                     self.__class__.__name__, log.value(), err,
                                     traceback.format_exc())
        finally:
            # Close down consumer to commit final offsets.
            self.consumer.close()

    def reset(self):
        """
        Resets drain3 state for all services(locally and on redis)
        """
        # Removing redis entries
        for drain3_object in list(self.drain3_objects.values()):
            drain3_object.persistence_handler.delete_state()
        self.drain3_objects.clear()
        logger.info("Drain3 state reset complete")
        self.last_reset_time = time.time()

    def shutdown():
        logger.info("Shutting down consumer")
        self.running = False
