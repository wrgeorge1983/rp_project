"""control_plane_v1.py
defines first version of control plane implementation"""

import asyncio
from ipaddress import ip_network, ip_interface, ip_address
import logging
log = logging.getLogger(__name__)
from typing import Sequence, Dict

from rp_static import utils
from rp_static.forwarding_plane_v1 import FIBNextHop, ForwardingPlane


GLOBAL_STATE = {
    'strict_config_handling': True
}


class ControlPlane:
    def __init__(self):
        self.fp = ForwardingPlane()
        self.loop = None
        self.interface_names = []

    async def async_init(self, state, loop):
        log.debug('entering ControlPlane.async_init()')
        self.loop = loop

        configs = await utils.async_get_configs_by_hostname(state.config_file_path,
                                                            state.topo_filename,
                                                            state.hostname)
        log.debug('configs collected')
        router_config = configs['router_config']
        topology_config = configs['topology']
        await self.fp.async_init(topology_config, state, loop)
        self.process_config(router_config)

    def process_config(self, config):
        self.config = config
        self.interface_names = config['interface_names']

        self.fp.interfaces = [
            {'name': key, 'config': self.process_interface_config(key, value)}
             for key, value in config['interfaces'].items()
        ]
        self.fp.add_fib_entries_from_interface_configs()

        try:
            self.process_static_protocol(config['protocols']['static'])
        except KeyError:
            pass

    def process_static_protocol(self, config: Dict):
        fp = self.fp
        for dest_str, next_hop_str in config.items():
            dest = ip_network(dest_str)
            next_hop =  FIBNextHop(ip_address(next_hop_str))
            fp.add_fib_entry(dest, next_hop)

    @staticmethod
    def process_interface_config(name, config):
        log.debug(f'Processing interface config for {name}')
        new_config = {}
        passthrough_items = [
            # 'proxy_arp'
        ]

        for key, value in config.items():
            if key == 'ipaddr':
                new_value = ip_interface(value)
            elif key in passthrough_items:
                new_value = value
            else:
                if GLOBAL_STATE['strict_config_handling']:
                    raise NotImplementedError(f'Unsupported configuration item {key} found in config for interface {name}')
                new_value = value

            new_config[key] = new_value
        return new_config

    def l2_send_text(self, msg_text, interface_names: Sequence[str] = None):
        if interface_names is None:  # None == "all"
            interface_names = self.interface_names

        for interface_name in interface_names:
            self.fp.l2_send(msg_text, interface_name)


def start_cp(state):
    log.debug('entering start_cp()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()

    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    log.info(f'Created fib: {repr(cp.fp.fib)}')

    test_destinations = [
        '192.168.1.1',
        '10.0.1.1',
        '10.0.1.8',
        '10.1.8.5',
        '10.8.0.3'
    ]

    for dest in test_destinations:
        dest_addr = ip_address(dest)
        try:
            result = cp.fp.fib_lookup(dest_addr, recursive=True)
        except ValueError:
            result = 'NOT FOUND'
        log.info(f'looking up {dest} in fib: {repr(result)}')


def listen(state):
    log.debug('entering listen()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()

    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    def cb(message):
        print(message)

    cp.fp.register_interface_listener(
        cb=cb,
        logical_interface_name='E0',
        msg_filter=lambda x: 'EST' in x.content
    )

    loop.create_task(utils._loop_timeout(state.timeout, loop))
    with utils.LoopExceptionHandler(loop):
        loop.run_forever()


def pulsar(state, message):
    log.debug('entering pulsar()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()
    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    loop.create_task(utils._loop_timeout(state.timeout, loop))

    async def pulse(pulse_interval:int, msg_text, interface_names=None):
        while True:
            log.debug('pulse() is about to sleep')
            await asyncio.sleep(pulse_interval)
            log.debug('pulse() is about to send')
            cp.l2_send_text(msg_text, interface_names=interface_names)
            log.debug('pulse() sent')

    log.debug('Creating pulsar task')
    loop.create_task(
        pulse(3, message, ('E0', 'E2'))
    )

    with utils.LoopExceptionHandler(loop):
        loop.run_forever()


