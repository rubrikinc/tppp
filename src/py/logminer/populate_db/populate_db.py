import pymysql.cursors
import logging
import os
import sys
import pathlib
import jsonpickle
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass
from common.entry_point import EntryPoint  # noqa

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence
from drain3_consumer.template_miner_intervalpersistence import TemplateMinerWithIntervalPersistence  # NOQA

saved_object_path = '/logminer/drain3_obj'
DRAIN_OBJECT_NAME_DELIMITER = '_'

logger = logging.getLogger()

PATTERN_INSERT_TEMPLATE = "INSERT INTO patterns VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (timestamp, svc, version, pat_id) DO NOTHING;"

@dataclass
class Pattern:
    """Data-class for pattern"""
    pat_id: str
    pattern: str
    size: float


def get_conn():
    settings = EntryPoint.settings_dict
    try:
        conn = pymysql.connect(
            database=settings['db_config']['database'],
            user=settings['db_config']['user'],
            password=settings['db_config']['password'],
            host=settings['db_config']['host'],
            port=settings['db_config']['port']
        )
        logger.info("DB Connection Successful")
        return conn
    except Exception as e:
        logger.info(e)


def extract_svc_version(name):
    return name.split(DRAIN_OBJECT_NAME_DELIMITER)[:2]


def push_patterns(cur):
    for root, _, files in os.walk(saved_object_path):
        for name in files:
            patterns = []
            file_path = os.path.join(root, name)
            svc, version = extract_svc_version(name)
            state = pathlib.Path(file_path).read_bytes()
            drain = jsonpickle.loads(state, keys=True)
            total_logs = 0
            for cluster in list(drain.id_to_cluster.values()):
                pattern = Pattern(cluster.cluster_id,cluster.get_template(),cluster.size)
                total_logs += pattern.size
                patterns.append(pattern)

            for pattern in patterns:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cur.execute(PATTERN_INSERT_TEMPLATE, [timestamp, svc, version,
                            pattern.pat_id, pattern.pattern,
                            pattern.size/total_logs])


if __name__ == "__main__":
    conn = get_conn()
    if not conn:
        logger.info("Abort! Connection was not established")
        sys.exit()

    cur = conn.cursor()

    push_patterns(cur)

    cur.close()
    conn.commit()
    conn.close()
