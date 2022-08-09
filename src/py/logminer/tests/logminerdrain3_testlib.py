"""Script to test drain3 code locally."""
from __future__ import absolute_import

import atexit
from builtins import object
import logging
import os
from shutil import copy
from shutil import copytree
from shutil import ignore_patterns
from shutil import rmtree
import socket
import subprocess
import sys
import tempfile
import traceback

import jinja2
import requests
from retrying import retry

LOG_FORMAT = '%(asctime)s %(levelname)s ' + \
    '<%(process)d.%(threadName)s> [%(name)s] %(funcName)s:%(lineno)d %(' \
    'message)s'
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
log = logging.getLogger(__name__)

SRC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
EXTRA_FILES = ['deploy/Dockerfile', 'requirements.txt']

sys.path.append(os.path.join(SRC_PATH, 'logminerdrain3'))

from common.entry_point import EntryPoint


class Drain3TestLib(object):
    """Library to make it easier to run drain3 testcases."""

    def __init__(self):
        """Initialize."""

        EntryPoint.load_yaml_settings(
            os.path.join(os.path.dirname(__file__),
                         '../config', 'settings_test.yaml'))
        atexit.register(self.cleanup)

    @staticmethod
    def stage_files():
        """Stage the drain3 consumer files."""
        staging_dir = os.path.join(tempfile.mkdtemp(), 'drain3')

        # Copy all drain3 files
        copytree(os.path.join(SRC_PATH, 'logminerdrain3'),
                 os.path.join(staging_dir, 'logminerdrain3'),
                 ignore=ignore_patterns('*.pyc', '*.sh', 'test'))
        if EXTRA_FILES:
            for file in EXTRA_FILES:
                copy(os.path.join(SRC_PATH, file), staging_dir)

        return staging_dir

    @staticmethod
    def docker_build():
        """Build a local Docker image for drain3 consumer."""

        # Stage all source files in a temporary directory
        staging_dir = Drain3TestLib.stage_files()

        # Save the current working dir
        cwd = os.getcwd()
        os.chdir(staging_dir)
        # Run the build command
        build_cmd = ['sudo', 'docker', 'build', '-t',
                     'logminerdrain3:local', '-f', 'Dockerfile', '.']
        try:
            subprocess.check_call(build_cmd, stderr=subprocess.STDOUT)
        finally:
            # Revert back to old working dir and remove the staged files
            os.chdir(cwd)
            rmtree(staging_dir)

    @staticmethod
    def render_jinja_file(input_file, output_file, render_kwargs=None):
        """Render j2 file with the required variables."""
        render_kwargs = render_kwargs or {}
        path, filename = os.path.split(input_file)
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(path))

        text = env.get_template(filename).render(env=os.environ,
                                                 **render_kwargs)
        with open(output_file, 'w') as f:
            f.write(text)

    @staticmethod
    def launch_service():
        """Launch all services necessary for drain3 using docker-compose."""
        # Generate compose file with any necessary variables
        compose_file_j2 = os.path.join(os.path.dirname(__file__),
                                       "docker-compose.yml.j2")
        compose_file, _, _ = compose_file_j2.partition(".j2")
        # Generate drain3 config file with any necessary variables
        drain3_file_j2 = os.path.join(os.path.dirname(__file__),
                                      "..", "config", "drain3.ini.j2")
        drain3_file, _, _ = drain3_file_j2.partition(".j2")
        # Generate info to be used by Kafka container to automatically create
        # topics
        producer = EntryPoint.settings_dict['drain3_test_producer']
        consumer = EntryPoint.settings_dict['drain3_consumer']
        # Notation is "TopicName:NumPartitions:NumReplicas"
        topics_info = [
            "%s:%d:%d" % (producer['topic'], producer['num_partitions'], 1),
            "%s:%d:%d" % (consumer['topic'], consumer['topic_partitions'], 1),
        ]
        render_kwargs = {
            "topics_csl": ",".join(topics_info),
        }
        Drain3TestLib.render_jinja_file(compose_file_j2, compose_file,
                                        render_kwargs=render_kwargs)

        render_kwargs = {
            "snapshot_interval_time": consumer['snapshot_interval_time']
        }
        Drain3TestLib.render_jinja_file(drain3_file_j2, drain3_file,
                                        render_kwargs=render_kwargs)
        launch_cmd = ['sudo', 'docker-compose', '-p', 'drain3', '-f',
                      compose_file, "up", "-d"]
        subprocess.check_output(launch_cmd)
        log.info("Launched all services")

    @staticmethod
    def check_conn_listening(ip_addr, port):
        """Check if connections are being accepted on <ip_addr:port>."""
        sock = socket.socket()
        sock.settimeout(5)
        sock.connect((ip_addr, port))
        sock.close()

    # Takes some time for the ES container to be up
    @staticmethod
    @retry(stop_max_attempt_number=6, wait_fixed=30000)
    def wait_for_es_up():
        """Check if ES container is up and accepting connections."""
        try:
            Drain3TestLib.check_conn_listening('127.0.0.1', 9200)
            log.info("ES container is up")
        except Exception as e:
            log.exception("ES container is not up. Retrying")
            raise e

    # Takes some time for the Kafka container to be up
    @staticmethod
    @retry(stop_max_attempt_number=6, wait_fixed=30000)
    def wait_for_kafka_up():
        """Check if Kafka container is up and accepting connections."""
        try:
            Drain3TestLib.check_conn_listening('kafka', 9092)
            log.info("Kafka container is up")
        except Exception as e:
            log.exception("Kafka container is not up. Retrying")
            raise e

    # Takes some time for the Flask container to be up
    @staticmethod
    @retry(stop_max_attempt_number=6, wait_fixed=30000)
    def wait_for_flask_up():
        """Check if Flask container is up and accepting requests."""
        try:
            req = requests.get("http://127.0.0.1:5000/health")
            assert req.ok
            log.info("Flask container is up")
        except Exception as e:
            log.exception("Flask container is not up. Retrying")
            raise e

    @staticmethod
    def setup():
        """Setups necessary stuff for running testcases."""

        # Build local Docker image
        Drain3TestLib.docker_build()

        # Launch all services needed by drain3
        Drain3TestLib.launch_service()

        # Wait for critical services to be up
        # Drain3TestLib.wait_for_kafka_up()
        # Drain3TestLib.wait_for_flask_up()

    def run(self):
        """Run testcases."""

        Drain3TestLib.setup()

        # Run testcases
        self.run_testcases()

        # If we reached here, all testcases passed
        log.info("\n\n\033[32m PASS \033[0m: All testcases passed\n")

    def run_testcases(self):
        """Override this method and add your testcases here."""
        raise NotImplementedError

    def cleanup(self):
        """Shutdown all services before ending test."""

        # Shutdown services launched via docker-compose
        compose_file = os.path.join(os.path.dirname(__file__),
                                    "docker-compose.yml")
        subprocess.check_output(["sudo", "docker-compose", "-p", "drain3",
                                 "-f", compose_file, "down"])

        # Delete all containers. Without this, we end up with stale DAGs, jobs
        # state & stats.
        subprocess.check_output(["sudo", "docker-compose", "-p", "drain3",
                                 "-f", compose_file, "rm", "-f"])


def run_tests(test_class):
    """Run test classes derived from Drain3TestLib with error handling."""
    try:

        test_class.run()
    except Exception as e:
        log.error("\033[31m FAIL \033[0m: Saw error while running %s: %s",
                  test_class.__class__.__name__, e)
        log.error(traceback.format_exc())
        raise e
