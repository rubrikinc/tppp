"""
Wrapper of the TemplateMiner in drain3 - add persistence on specified interval.
"""
import base64
import logging
import time
import traceback

from drain3.drain import LogCluster
from drain3.template_miner import TemplateMiner
import jsonpickle

logger = logging.getLogger(__name__)


class TemplateMinerWithIntervalPersistence(TemplateMiner):
    """
    Default TemplateMiner saves state at every cluster update.
    Wrapper class to save state only at snapshot interval.
    """

    def __init__(self, persistence, config):
        super().__init__(persistence, config)

    def get_snapshot_reason(self, change_type=None, cluster_id=0):
        """
        Gives snapshot reason only if snapshot interval reached.
        This method before overriding returned not None on any cluster update
        resulting in snapshot being taken for every cluster update as well.
        """

        diff_time_sec = time.time() - self.last_save_time
        #if diff_time_sec >= self.config.snapshot_interval_minutes * 60:
        return "periodic"

        #return None

    def save_state(self, snapshot_reason):
        state = jsonpickle.dumps(self.drain, keys=True).encode('utf-8')
        if self.config.snapshot_compress_state:
            state = base64.b64encode(zlib.compress(state))

        logger.info(f"Persisting state of {len(self.drain.clusters)} clusters "
                     f"with {self.drain.get_total_cluster_size()} messages, "
                     f"reason: {snapshot_reason}")
        try:
            self.persistence_handler.save_state(state)
        except Exception as err:
            logger.error('%s: Failed to persist to Redis '
                         'Exception: %s ST: %s',
                         self.__class__.__name__, err,
                         traceback.format_exc())

    def match(self, log_message: str) -> LogCluster:

        """
          Match against an already existing cluster.
          Match shall be perfect (sim_th=1.0).
          New cluster will not be created as a result of this call.
          Method before overriding did not update cluster size on match and
          did not save snapshot at specified interval.
          """
        masked_content = self.masker.mask(log_message)
        matched_cluster = self.drain.match(masked_content)
        snapshot_reason = self.get_snapshot_reason()
        if snapshot_reason:
            self.save_state(snapshot_reason)
            self.last_save_time = time.time()
        if matched_cluster:
            cluster_id = matched_cluster.cluster_id
            self.drain.id_to_cluster[cluster_id].size += 1
        return matched_cluster
