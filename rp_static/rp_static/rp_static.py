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


@click.command()
@click.argument('config_file',
                envvar='RP_CONFIG_FILE',
                required=True,
                type=click.File('r'))
@click.argument('topology_file',
                envvar='RP_TOPOLOGY_FILE',
                required=True,
                type=click.File('r'))
def main(config_file, topology_file):
    log.info(f'Using config file: {config_file.name}')
    log.info(f'Using topology file: {topology_file.name}')
    config = yaml.load(config_file)
    topology = yaml.load(topology_file)
    log.info(f'Got config: {config}')
    log.info(f'Got topology: {topology}')





