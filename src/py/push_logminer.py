"""Script to setup Logminerdrain3 in AWS environments."""

from __future__ import absolute_import
from __future__ import print_function

from builtins import object
import os
import subprocess
import tempfile
import sys
import argparse
from typing import Tuple

import logging  # noqa
from shutil import copy, copytree, ignore_patterns, rmtree  # noqa

import jinja2
import boto3
import yaml


log = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..'))


class LogminerAws(object):
    """Class for building Logminer docker-image and pushing in ECR"""

    def __init__(self, args):
        """Create helper to deploy Logminerdrain3 on AWS."""
        self.args = args

    def stage_files(self, dirs_to_copy, extra_files_to_copy=[]):
        """Stage the  container files."""
        staging_dir = tempfile.mkdtemp()
        for src_dir in dirs_to_copy:
            src_path = os.path.join(REPO_ROOT, src_dir)
            dst_path = os.path.join(staging_dir, os.path.basename(src_dir))
            copytree(src_path, dst_path,
                     ignore=ignore_patterns('*.pyc', 'test'))
        if extra_files_to_copy:
            for file in extra_files_to_copy:
                copy(os.path.join(REPO_ROOT, file), staging_dir)
        return staging_dir

    def get_default_image_tag(self):
        """Return default image tag"""
        return "image_tag"

    def render_jinja_file(self, input_file, output_file, render_kwargs=None,
                          undefined=None):
        """Render output file from Jinja template"""
        render_kwargs = render_kwargs or {}
        path, filename = os.path.split(input_file)
        if undefined:
            # The caller expects to render undefined variables a certain way.
            # Fulfill their expectations
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(path),
                                     undefined=undefined)
        else:
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(path))

        text = env.get_template(filename).render(env=os.environ,
                                                 **render_kwargs)
        with open(output_file, 'w') as f:
            f.write(text)

    def check_and_get_settings(self) -> Tuple[bool, str]:
        """Get the settings from yaml"""
        settings_file_name = "settings.yaml"
        settings_path = os.path.join("logminer", "config",
                                     settings_file_name)
        # Check if settings.yaml file exists
        if os.path.isfile(settings_path) is False:
            if os.path.isfile(settings_path) is False:
                log.error("Settings file not found")
            return (False, "")
        log.info("Settings file found")
        with open(settings_path) as file:
            settings = yaml.safe_load(file)
        return (True, settings)

    def docker_build_drain3_consumer_image(self, staging_dir, image_tag=None):
        """Build docker-image for Logminer"""
        image_tag = image_tag or self.get_default_image_tag()

        # Save the current working dir
        cwd = os.getcwd()
        os.chdir(staging_dir)
        settings_file_name = "settings.yaml"
        settings_path = os.path.join("logminer", "config",
                                     settings_file_name)
        with open(settings_path) as file:
            settings = yaml.safe_load(file)
        time = settings['drain3_consumer']['snapshot_interval_time']
        self.render_jinja_file(
            os.path.join("logminer", "config", "drain3.ini.j2"),
            os.path.join("logminer", "config", "drain3.ini"),
            {
                "snapshot_interval_time": time
            })
        print(staging_dir)
        consumer_name = settings['drain3_consumer']['consumer_name']

        build_cmd = ['sudo', 'docker', 'build', '-t',
                     '%s:%s' % (consumer_name, image_tag), '-f', 'Dockerfile',
                     '.']
        try:
            subprocess.check_call(build_cmd, stderr=subprocess.STDOUT)
        finally:
            # Revert back to old working dir and remove the staged files
            os.chdir(cwd)
            rmtree(staging_dir)

    def run_cmd(self, cmd, dry_run=False):
        """Execute ECS command."""
        print(cmd)
        if dry_run:
            log.info("Dry run mode (Not launching): %s" % " ".join(cmd))
        else:
            subprocess.check_call(cmd)

    def push_docker_image_to_ecr_repo(self, image_name, image_tag, ecr_repo_url,
                                  dry_run=False):
        """Push local Docker image to ECR repository.

        Arguments:
        - image_name: Docker image name
        - image_tag: Docker image tag. The docker image name & tag are combined to
        identify the Docker image locally.
        - ecr_repo_url: The ECR repo to which the Docker image will be pushed. Eg.
        aws_account_id.dkr.ecr.region.amazonaws.com.

        Keyword arguments:
        - dry_run: Don't actually run the commands. Just print them
        """
        target_repo = '%s/%s:%s' % (ecr_repo_url, image_name, image_tag)

        tag_cmd = ['sudo', 'docker', 'tag',
                '%s:%s' % (image_name, image_tag), target_repo]
        push_cmd = ['sudo', 'docker', 'push', target_repo]

        try:
            self.run_cmd(tag_cmd)
            self.run_cmd(push_cmd)
        except subprocess.CalledProcessError:
            log.info('Re-authenticate docker client to AWS ecr registry')
            credentials = subprocess.check_output(
                ['aws', 'ecr', 'get-login', '--no-include-email'],
                stderr=subprocess.STDOUT).decode('utf8')

            if not credentials.startswith('docker login'):
                raise Exception("Received credentials should start " +
                                "with 'docker build'. Received %s .." +
                                "quitting" % credentials)

            # This essentially tries to login first to ECR
            subprocess.check_call(['sudo'] + credentials.strip().split(' '))

            # Try the push command again after logging in
            subprocess.check_call(push_cmd)

    def render_helm_values(self, ecr_repo_url, image_name):
        """Render helm values.yaml file with the Docker-Image location"""
        helm_values_path = os.path.join(REPO_ROOT, "deploy", "helm",
                            "logminer",
                            "values.yaml.j2")
        output_path = os.path.join(REPO_ROOT, "deploy", "helm",
                            "logminer",
                            "values.yaml")
        image_location = '%s/%s' % (ecr_repo_url, image_name)
        self.render_jinja_file(helm_values_path, output_path,
            {"image_location": image_location})

        pass

    def run(self):
        """Use default image tag"""
        image_tag = self.get_default_image_tag()
        ok, settings = self.check_and_get_settings()
        if not ok:
            log.error("Settings file not found, ending script...")
            return

        staging_dir = self.stage_files(
            dirs_to_copy=[os.path.join(REPO_ROOT, "src/py/logminer")],
            extra_files_to_copy=[os.path.join(REPO_ROOT, "deploy/docker/logminer/Dockerfile")])

        self.docker_build_drain3_consumer_image(staging_dir,
                                                image_tag=image_tag)

        self.push_docker_image_to_ecr_repo(
            image_name=settings['drain3_consumer']['consumer_name'],
            image_tag=image_tag,
            ecr_repo_url=settings['drain3_consumer']['ecr_repo_url']
            )
        self.render_helm_values(
            ecr_repo_url=settings['drain3_consumer']['ecr_repo_url'],
            image_name=settings['drain3_consumer']['consumer_name'])


def s3_download_yamls(s3_location) -> bool:
    """Download yaml files from s3 location."""
    s3 = boto3.client("s3")
    path_prefix = "logminer/config/"
    s3.download_file(s3_location[0], s3_location[1] + "/settings.yaml",
                        path_prefix + "settings.yaml")
    return True


def s3_upload_yamls(s3_location) -> bool:
    """Upload yaml files to s3 location."""
    s3 = boto3.client("s3")
    path_prefix = "logminer/config/"
    s3.upload_file(path_prefix + "settings.yaml", s3_location[0],
                    s3_location[1] + "/settings.yaml")
    return True


if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Build and prep script for Logminer.")
    parser.add_argument(
        "--operation", "-op",
        help="Specify the type of operation",
        choices=["build", "download_cfg", "upload_cfg"],
        default="build")
    parser.add_argument(
        "--s3_location", "-s3",
        nargs=2,
        help="S3 location to download/upload the required yaml files, " + \
                "provide bucket-name and object-name as the two arguments",
        default=[])
    args = parser.parse_args()

    if len(args.s3_location) == 2:
        if args.operation == "download_cfg":
            s3_download_yamls(s3_location=args.s3_location)
            log.info("Downloaded deployment configs from s3")
            sys.exit(0)
        elif args.operation == "upload_cfg":
            s3_upload_yamls(s3_location=args.s3_location)
            log.info("Uploaded deployment configs to s3")
            sys.exit(0)
        else:
            log.info("S3 option can only be used with download/upload" + \
                        " operation type")
            sys.exit(0)
    elif args.operation in ["download_cfg", "upload_cfg"]:
        log.error("Cannot download/upload deployment configs without" + \
                    " the two s3 parameters")
        sys.exit(1)

    if args.operation == "build":
        LogminerAws([]).run()
        log.info("Successfully built and prepped Logminer helm-chart for" + \
                    " deployment")
        sys.exit(0)
