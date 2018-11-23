import logging

import yaml
import click

def get_logger():
    sh = logging.StreamHandler()
    logger = logging.getLogger(__name__)
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)
    return logger

log = get_logger()


def get_configs(config_file, topology_file):
    log.info(f'Using config file: {config_file.name}')
    log.info(f'Using topology file: {topology_file.name}')
    config = yaml.load(config_file)
    topology = yaml.load(topology_file)
    log.debug(f'Got config: \n{yaml.dump(config)}')
    log.debug(f'Got topology: \n{yaml.dump(topology)}')
    return {
        'router_config': config,
        'topology': topology
    }


@click.command()
@click.option('-c', 'config_file',
                envvar='RP_CONFIG_FILE',
                required=True,
                type=click.File('r'))
@click.option('-t', 'topology_file',
                envvar='RP_TOPOLOGY_FILE',
                required=True,
                type=click.File('r'))
@click.option('--debug', 'debug',
                envvar='RP_DEBUG',
                default=False,
                is_flag=True)
def main(config_file, topology_file, debug):
    if debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(config_file, topology_file)






