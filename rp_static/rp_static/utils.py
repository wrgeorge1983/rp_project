import yaml
import logging

log = logging.getLogger(__name__)





def get_configs(config_file, topology_file):
    log.debug(f'entered get_configs()')
    if config_file is not None:
        log.info(f'Using config file: {config_file.name}')
        config = yaml.load(config_file)
    else:
        config = {}
    log.info(f'Using topology file: {topology_file.name}')
    topology = yaml.load(topology_file)
    log.debug(f'Got config: \n{yaml.dump(config)}')
    log.debug(f'Got topology: \n{yaml.dump(topology)}')
    return {
        'router_config': config,
        'topology': topology
    }
