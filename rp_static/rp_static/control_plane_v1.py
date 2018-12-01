"""control_plane_v1.py
defines first version of control plane implementation"""

import logging
log = logging.getLogger(__name__)

from rp_static import generic_l2 as l2
from rp_static import utils



def start_cp(state):
    log.debug('entering start_cp()')
    configs = utils.get_configs_by_hostname(state.config_file_path,
                                            state.topology_file,
                                            state.hostname)


