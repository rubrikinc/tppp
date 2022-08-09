"""Deployer script for TPPP."""
import os
import sys
import logging
import argparse
import subprocess
from typing import Tuple
from pathlib import Path

import yaml
import boto3


logger = logging.getLogger()


class Deployer:
    """Deployer class for TPPP."""

    def __init__(self) -> None:
        with open("deploy.yaml", "r", encoding="utf-8") as file:
            self.deploy_values = yaml.safe_load(file)

    def check_for_awscli(self) -> bool:
        """Check if awscli is installed."""
        cmd = ["which", "aws"]
        return_code = subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        if return_code == 0:
            logger.debug("awscli is installed")
            return True
        else:
            logger.error("awscli is not installed")
        return False

    def check_for_kubectl(self) -> bool:
        """Check if kubectl is installed."""
        cmd = ["which", "kubectl"]
        return_code = subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        if return_code == 0:
            logger.debug("kubectl is installed")
            return True
        else:
            logger.error("kubectl is not installed")
        return False

    def check_for_helm(self) -> bool:
        """Check if helm is installed."""
        cmd = ["which", "helm"]
        return_code = subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        if return_code == 0:
            logger.debug("helm is installed")
            return True
        else:
            logger.error("helm is not installed")
        return False

    def check_for_vector_repo_helm(self) -> bool:
        """Check if the vector-repo is added in helm."""
        cmd = ["helm", "repo", "add", "vector", "https://helm.vector.dev"]
        return_code = subprocess.check_call(cmd)
        if return_code != 0:
            return False
        cmd = ["helm", "repo", "update"]
        return_code = subprocess.check_call(cmd)
        if return_code != 0:
            return False
        return True

    def check_for_vector(self) -> bool:
        """Check if vector is installed."""
        cmd = ["which", "vector"]
        return_code = subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        if return_code == 0:
            logger.debug("vector is installed")
            return True
        else:
            logger.error("vector is not installed")
        return False

    def check_dataplane_context(self, deploy_mode) -> bool:
        """Check sandbox context for dataplane."""
        cmd = ["kubectl", "config", "current-context"]
        output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        if output != self.deploy_values['context'][deploy_mode]:
            logger.error("Current context doesn\'t match with deploy-mode: %s", deploy_mode)
            return False
        logger.info("Current context matches with deploy-mode: %s", deploy_mode)
        return True

    def check_access_to_kubernetes(self) -> bool:
        """Check if kubernetes can be accessed."""
        cmd = ["kubectl", "get", "all"]
        output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        if output.startswith("error"):
            logger.error("Cannot access K8s cluster, please check your .kube/config")
            logger.error("\n%s", output)
            return False
        logger.info("K8s cluster can be accessed\n%s", output)
        return True

    def check_values_file(self, deploy_mode) -> Tuple[bool, str]:
        """Check if corresponding values file exist for the deploy_mode."""
        values_path = self.deploy_values["values_file"][deploy_mode]
        if os.path.isfile(values_path) is False:
            logger.error("Values file not found for deploy_mode: %s", deploy_mode)
            return (False, "")
        logger.info("Values file found for deploy_mode: %s", deploy_mode)
        return (True, values_path)

    def get_vector_config(self, deploy_mode) -> str:
        """Get vector config from the values file."""
        ok, values_path = self.check_values_file(deploy_mode)
        if ok is False:
            return ""
        with open(values_path, "r", encoding="utf-8") as file:
            helm_values = yaml.safe_load(file)
        vector_config = helm_values["customConfig"]
        return vector_config

    def validate_vector_config(self, deploy_mode) -> bool:
        """Validate vector config from the values file."""
        if self.check_for_vector() is False:
            return False
        vector_config = self.get_vector_config(deploy_mode)
        tmp_config_path = "tmp_config.yaml"
        with open(tmp_config_path, "w", encoding="utf-8") as file:
            yaml.dump(vector_config, file, default_flow_style=False)
        cmd = ["vector", "validate", tmp_config_path]
        return_code = subprocess.call(cmd)
        if return_code != 0:
            return False
        return True

    def generate_graph(self, deploy_mode) -> bool:
        """Generate vector pipeline-graph from the values file"""
        if self.check_for_vector() is False:
            return False
        vector_config = self.get_vector_config(deploy_mode)
        tmp_config_path = "tmp_config.yaml"
        with open(tmp_config_path, "w", encoding="utf-8") as file:
            yaml.dump(vector_config, file, default_flow_style=False)
        cmd = ["vector", "graph", "--config",
                tmp_config_path]
        output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        with open("graph.out", "w", encoding="utf-8") as out_file:
            print(output, file=out_file)
        return True

    def deploy_dataplane(self, deploy_mode, operation) -> bool:
        """Deploy TPPP dataplane using the deploy_mode specified"""
        logger.info("Deploying TPPP dataplane in %s mode", deploy_mode)

        if self.check_dataplane_context(deploy_mode) is False:
            return False
        if self.check_access_to_kubernetes() is False:
            return False

        ok, values_path = self.check_values_file(deploy_mode)
        if ok is False:
            return False

        if operation == "upgrade":
            cmd = ["helm", "upgrade", "vector", "vector/vector",
                    "--version", self.deploy_values["vector"]["chart_version"],
                    "--values", values_path]
            output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        elif operation == "start":
            cmd = ["helm", "install", "vector", "vector/vector",
                    "--version", self.deploy_values["vector"]["chart_version"],
                    "--values", values_path]
            output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        elif operation == "stop":
            cmd = ["helm", "delete", "vector"]
            output = subprocess.check_output(cmd).decode("utf-8")[:-1]
        logger.info(output)
        return True


def s3_download_yamls(s3_location) -> bool:
    """Download yaml files from s3 location."""
    s3 = boto3.client("s3")
    s3.download_file(s3_location[0], s3_location[1] + "/deploy.yaml", "deploy.yaml")

    ## Create values folder for downloading the values.yaml into.
    Path("values").mkdir(parents=True, exist_ok=True)
    with open("deploy.yaml", "r", encoding="utf-8") as file:
        deploy_values = yaml.safe_load(file)
    for deploy_mode, path in deploy_values["values_file"].items():
        s3.download_file(s3_location[0],
            f"%s/values/values_%s.yaml" % (s3_location[1], deploy_mode), path)
    return True


def s3_upload_yamls(s3_location) -> bool:
    """Upload yaml files to s3 location."""
    s3 = boto3.client("s3")
    s3.upload_file("deploy.yaml", s3_location[0], s3_location[1] + "/deploy.yaml")
    with open("deploy.yaml", "r", encoding="utf-8") as file:
        deploy_values = yaml.safe_load(file)
    for deploy_mode, path in deploy_values["values_file"].items():
        s3.upload_file(path, s3_location[0],
            f"%s/values/values_%s.yaml" % (s3_location[1], deploy_mode))
    return True


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    parser = argparse.ArgumentParser(description="Deploy script for TPPP.")
    parser.add_argument(
        "--deploy_mode", "-dm",
        help="Deployment mode (sandbox/prod)",
        choices=["sandbox", "prod"],
        default="sandbox")
    parser.add_argument(
        "--operation", "-op",
        help="Specify the type of operation",
        choices=["upgrade", "start", "stop", "validate", "graph",
                 "download_cfg", "upload_cfg"],
        default="graph")
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
            logger.info("Only downloaded deployment configs from s3")
            sys.exit(0)
        elif args.operation == "upload_cfg":
            s3_upload_yamls(s3_location=args.s3_location)
            logger.info("Uploaded deployment configs to s3")
            sys.exit(0)
        else:
            logger.info("S3 option can only be used with download/upload" + \
                " operation type")
            sys.exit(0)
    elif args.operation in ["download_cfg", "upload_cfg"]:
        logger.error("Cannot download/upload deployment configs without" + \
                " the two s3 parameters")
        sys.exit(1)

    deployer = Deployer()

    if args.operation == "graph":
        deployer.generate_graph(deploy_mode=args.deploy_mode)
        sys.exit(0)

    if args.operation == "validate":
        deployer.validate_vector_config(deploy_mode=args.deploy_mode)
        sys.exit(0)

    if (deployer.check_for_awscli() and deployer.check_for_kubectl() and \
            deployer.check_for_helm() and \
                deployer.check_for_vector_repo_helm) is False:
        logger.error("Please install the cli packages and try again")
        sys.exit(1)
    logger.info("All cli tools are found, proceeding with deployment")

    if deployer.deploy_dataplane(deploy_mode=args.deploy_mode, \
            operation=args.operation) is False:
        logger.error("Failed to deploy tppp-dataplane")
        sys.exit(1)

    logger.info("Successfully deployed tppp-dataplane!")
    sys.exit(0)
