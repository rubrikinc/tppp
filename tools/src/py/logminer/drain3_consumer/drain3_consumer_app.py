"""Consumer for log clustering using drain3."""

from __future__ import absolute_import

import logging
import os
import sys

from absl import app
from drain3_consumer import Drain3Consumer

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from common.entry_point import EntryPoint  # noqa

logger = logging.getLogger()


class Drain3ConsumerApp(EntryPoint):

    def __init__(self):
        """Initialize."""

        EntryPoint.__init__(self)

    def start(self):
        """
        Initialize the write path and start the consumers.
        :return:
        """

        logger.info("Creating the Drain3 Consumer")
        drain3_consumer = Drain3Consumer(EntryPoint.settings_dict)
        logger.info("Starting to consume")
        drain3_consumer.start_consumer()


if __name__ == "__main__":
    app.run(Drain3ConsumerApp().run)
