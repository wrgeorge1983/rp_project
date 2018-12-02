import asyncio
from typing import Union
import os
import logging

import aiofiles
import yaml

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


def get_configs_by_hostname(config_file_path, topology_file, hostname):
    log.debug(f'entered get_configs_by_hostname()')
    config_filename = f'{hostname}.config.yml'
    log.debug(f'config_file_path: {config_file_path}; config_filename: {config_filename}')
    full_config_filename = os.path.join(config_file_path, config_filename)
    log.info(f'Using config file: {full_config_filename}')
    with open(full_config_filename) as infil:
        config = yaml.load(infil)

    log.info(f'Using topology file: {topology_file.name}')
    topology = yaml.load(topology_file)
    log.debug(f'Got config: \n{yaml.dump(config)}')
    log.debug(f'Got topology: \n{yaml.dump(topology)}')
    return {
        'router_config': config,
        'topology': topology
    }


async def async_get_configs_by_hostname(config_file_path, topology_filename, hostname):
    log.debug('entered async_get_configs_by_hostname')
    config_filename = f'{hostname}.config.yml'
    log.debug(f'config_file_path: {config_file_path}; config_filename: {config_filename}')
    full_config_filename = os.path.join(config_file_path, config_filename)
    full_topology_filename = os.path.join(config_file_path, topology_filename)
    log.info(f'Using config file: {full_config_filename} and topology file: {full_topology_filename}')

    async with aiofiles.open(full_config_filename) as infil:
        contents = await infil.read()
    config = yaml.load(contents)

    async with aiofiles.open(full_topology_filename) as infil:
        contents = await infil.read()
    topology = yaml.load(contents)

    log.debug(f'Got config: \n{yaml.dump(config)}')
    log.debug(f'Got topology: \n{yaml.dump(topology)}')
    return {
        'router_config': config,
        'topology': topology
    }


class LoopExceptionHandler:
    def __init__(self, loop: Union[asyncio.BaseEventLoop, asyncio.AbstractEventLoop]):
        self.loop_state = {}
        self.loop = loop

    # TODO: Make this handle more than one possible exception?

    def handler(self, loop, context):
        log.debug('Handling exception in event loop')
        exc = context.get('exception')
        if exc:
            log.error('Error handled, stopping event loop')
            loop.stop()
            # if not isinstance(exc, asyncio.ExitMainLoop):
            # Store the exc_info so we can re-raise after the loop stops
            import sys
            exception_info = sys.exc_info()
            if exception_info == (None, None, None):
                exception_info = exc
            self.loop_state['exception_info'] = exception_info
        else:
            loop.default_exception_handler(context)

    def react(self):
        exception_info = self.loop_state.get('exception_info')
        if exception_info is not None:
            log.debug('Exception detected in event loop')
            if isinstance(exception_info, (list, tuple)):
                raise exception_info[0](exception_info[1]).with_traceback(exception_info[2])
                # self._exc_info = None
            elif isinstance(exception_info, BaseException):
                raise exception_info
            else:
                log.debug(f'got this exception_info: {repr(exception_info)}')
                raise Exception(str(exception_info))

    def __enter__(self):
        log.debug('Entering LoopExceptionHandler Context Manager')
        self.loop.set_exception_handler(self.handler)

    def __exit__(self, type, value, traceback):
        log.debug('Exiting LoopExceptionHandler Context Manager')
        self.react()
        self.loop.set_exception_handler(self.loop.default_exception_handler)
