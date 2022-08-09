"""
Script to test drain3  code locally.
Don't run directly. Run run_systest.sh to run sys tests.
"""
from __future__ import absolute_import

import json
import logging
import time

from logminerdrain3_testlib import Drain3TestLib
from logminerdrain3_testlib import LOG_FORMAT
from logminerdrain3_testlib import run_tests
import redis
import requests
from retrying import retry

logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
log = logging.getLogger(__name__)


class Drain3Systest(Drain3TestLib):
    """Test to make sure E2E correctness of Drain3."""

    def __init__(self):
        """Initialize test class."""

        super().__init__()

    @retry(stop_max_attempt_number=10, wait_fixed=30000)
    def check_redis_persistence(self):
        """Check that persistence to redis is successful."""

        try:
            r = redis.Redis(host='localhost',
                            port=7071,
                            db=0,
                            password='',
                            ssl=False)
            keys = list(r.keys())
            log.info("Keys in Redis:")
            for key in keys:

                log.info(key)

            assert len(keys) != 0, \
                "No keys in Redis"

            log.info("Redis persistence validated")
        except Exception as e:
            log.error(e)
            raise e

    @retry(stop_max_attempt_number=10, wait_fixed=30000)
    def check_flask_api_health(self):
        """Check that flask app is running."""

        log.info("Checking flask app health")
        req = requests.get("http://localhost:5000/health")
        assert req.status_code == 200, "Flask instance is not up"

    @retry(stop_max_attempt_number=10, wait_fixed=30000)
    def check_flask_api_global_patterns(self):
        """Check if fetching patterns and getting top patterns is working."""
        time.sleep(120)
        log.info("Check top global patterns")
        limit = 2
        url = "http://localhost:5000/top-patterns" \
              "?limit={}&service={}&format={}"
        req = requests.get(url.format(limit,
                                      "Global", "json"))
        response = json.loads(req.text)
        if(response.get('errors')):
            log.info(response)
        assert response['status'] == 'Successful' and \
               len(response['patterns']) == limit, \
            "Failed to fetch global patterns"

    @retry(stop_max_attempt_number=10, wait_fixed=30000)
    def check_flask_api_service_patterns(self):
        """Check if fetching  top patterns for a service is working."""

        log.info("Check top service  patterns")
        limit = 1
        service = 'ReplicationMain'
        url = "http://localhost:5000/top-patterns" \
              "?limit={}&service={}&format={}"
        req = requests.get(url.format(limit,
                                      service, "json"))
        response = json.loads(req.text)
        if(response.get('errors')):
            log.info(response)
        assert response['status'] == 'Successful' and \
               len(response['patterns']) == limit and \
               service in response['patterns'][0]['pattern'], \
            "Failed to fetch {} patterns".format(service)

    def run_testcases(self):
        """Run drain3 and verify persistence."""

        self.check_redis_persistence()
        self.check_flask_api_health()
        self.check_flask_api_global_patterns()
        self.check_flask_api_service_patterns()

if __name__ == '__main__':
    run_tests(Drain3Systest())
