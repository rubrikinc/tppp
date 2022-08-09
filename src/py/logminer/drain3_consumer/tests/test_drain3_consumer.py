"""Unit tests for Drain3Consumer."""
from __future__ import absolute_import

import json
import os
import sys
import time
import unittest

import mock

sys.path.append(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

sys.path.append(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..'))

class TestDrain3Consumer(unittest.TestCase):
    """Basic test for LogminerDrain3Consumer."""

    def setUp(self):
        """Initialize the LogminerDrain3Consumer."""
        # Avoid drain3 global imports to avoid unit test failures
        from common.entry_point import EntryPoint  # noqa
        EntryPoint.load_yaml_settings(os.path.dirname(__file__) +
                                      '/test_settings.yaml')

        self.persistence = mock.MagicMock()
        self.persistence.load_state.return_value = None
        self.config = None
        self.consumer = None

    def start_consumer(self):
        """Start LogminerDrain3Consumer."""
        # Avoid drain3 global imports to avoid unit test failures
        from common.entry_point import EntryPoint  # noqa
        from drain3.template_miner_config import TemplateMinerConfig  # noqa
        from drain3_consumer.drain3_consumer import Drain3Consumer  # noqa
        self.config = TemplateMinerConfig()
        self.config.load(os.path.join(os.path.dirname(__file__),
                                      "test_drain3.ini"))

        self.consumer = Drain3Consumer(EntryPoint.settings_dict,
                                       self.persistence,
                                       self.config)

    # Skipping unit tests in arc unit
    @unittest.skip("python3 not supported in arc unitest run")
    def test_process_logs_drain3(self):
        """Checks that process_logs() processes logs correctly."""

        self.start_consumer()

        # TEST1: verify object per service
        msg = '{"Severity": 3,' \
              '"Class": "src/cpp/code/utils/scoped_profile_context.cpp:47",' \
              '"Version": "5.3.1-p3-18910", "Logger": "ReplicationMain", ' \
              '"Payload": "Attempting to set an empty job context"}'
        self.consumer.process_log(json.loads(msg))
        self.assertTrue("ReplicationMain" in self.consumer.drain3_objects)
        self.persistence.reset_mock()

        # TEST2: Verify persistence on snapshot interval(test_drain3.ini)
        msg = '{"Severity": 3,' \
              '"Class": "src/cpp/code/utils/scoped_profile_context.cpp:47",' \
              '"Version": "5.3.1-p3-18910", "Logger": "ReplicationMain", ' \
              '"Payload": "Attempting to set an empty job context"}'
        self.consumer.process_log(json.loads(msg))
        service_drain3 = self.consumer.drain3_objects["ReplicationMain"]
        self.assertEqual(service_drain3.config.snapshot_interval_minutes, 1)
        time.sleep(60)
        self.consumer.process_log(json.loads(msg))
        self.assertEqual(self.persistence.save_state.call_count, 1)
        self.persistence.reset_mock()

        # TEST3: Verify switch to fast match on training time end
        # training time in settings yaml file: 2 min
        msg = '{"Severity": 3,' \
              '"Class": "src/cpp/code/utils/scoped_profile_context.cpp:47",' \
              '"Version": "5.3.1-p3-18910", "Logger": "ReplicationMain", ' \
              '"Payload": "Attempting to set an empty job context"}'
        time.sleep(60)
        self.consumer.process_log(json.loads(msg))
        self.assertFalse(self.consumer.training)

    def run_unittests(self):
        """
        Run this method directly to force run unit tests outside arc unit
        """
        # All unit testcases should be added here
        self.setUp()
        self.test_process_logs_drain3()
        self.tearDown()
