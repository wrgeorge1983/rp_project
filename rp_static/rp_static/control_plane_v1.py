"""control_plane_v1.py
defines first version of control plane implementation"""

import asyncio
from ipaddress import ip_network, ip_interface, ip_address
import logging
log = logging.getLogger(__name__)
from typing import Sequence, Dict

from rp_static import utils
from rp_static.forwarding_plane_v1 import FIBNextHop, ForwardingPlane
from rp_static.messages import NetworkMessage

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

        # It is deeply improper for us to be reaching into this object to add the interface configs ourselves like this:
        # self.fp.interfaces = [
        #     {'name': key, 'config': self.process_interface_config(key, value)}
        #      for key, value in config['interfaces'].items()
        # ]
        self.fp.process_interface_configs([
            {'name': key, 'config': self.process_interface_config(key, value)}
             for key, value in config['interfaces'].items()
        ])
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

    def l2_send_text(self, msg_text, interface_names: Sequence[str] = None):  # TODO: RENAME THIS if we want to continue using for content other than pure text
        if not interface_names:  # None == "all"
            interface_names = self.interface_names

        for interface_name in interface_names:
            self.fp.l2_send(msg_text, interface_name)

    def l3_send_text(self, msg_text, dst_ip_str: str, src_ip_str: str, specified_interface_name: str=None):
        dst_ip = ip_address(dst_ip_str)
        if src_ip_str is not None:
            src_ip = ip_address(src_ip_str)
        else:
            src_ip = None

        msg = NetworkMessage(content=msg_text, dest_ip=dst_ip, src_ip=src_ip)

        valid_egress_interface_names = [
            interface_name for interface_name in self.interface_names
            if self.fp.fib_lookup_validate(dst_ip, candidate=interface_name)
        ]
        if not valid_egress_interface_names:
            log.error(f'dst_ip: {dst_ip_str} wasn\'t valid on any egress interfaces, rejecting')
            return
        if specified_interface_name is not None:
            if specified_interface_name in valid_egress_interface_names:
                valid_egress_interface_names = [specified_interface_name]
            else:
                log.error(f'{specified_interface_name} isn\'t a valid egress_interface for {dst_ip_str}')
                return

        for interface_name in valid_egress_interface_names:
            self.fp.l3_send(msg, specified_logical_interface_name=interface_name)
        # self.fp.l3_send(msg, specified_logical_interface_name=e)
        # self.l2_send_text(msg, interface_names=egress_interface_names)


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


def listen(state, interface_name, filter_string):
    log.debug('entering listen()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()

    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    def cb(message):
        print(message)


    if interface_name:
        interface_names = [interface_name]
    else:
        interface_names = cp.interface_names

    if not filter_string:
        filter_string = ''

    for interface_name in interface_names:
        cp.fp.register_interface_listener(
            cb=cb,
            msg_filter=lambda x: filter_string in x.content,
            logical_interface_name=interface_name
        )

    loop.create_task(utils._loop_timeout(state.timeout, loop))
    with utils.LoopExceptionHandler(loop):
        loop.run_forever()


def l2_pulsar(state, message, interface_names):
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
            log.debug('pulse() is about to send')
            cp.l2_send_text(msg_text, interface_names=interface_names)
            log.debug('pulse() sent')
            log.debug('pulse() is about to sleep')
            await asyncio.sleep(pulse_interval)

    log.debug('Creating pulsar task')
    loop.create_task(
        pulse(3, message, interface_names)
    )

    with utils.LoopExceptionHandler(loop):
        loop.run_forever()


def l3_pulsar(state, message, dst_ip, src_ip, interface_names=None):
    log.debug('entering pulsar()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()
    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    loop.create_task(utils._loop_timeout(state.timeout, loop))

    async def pulse(pulse_interval:int, msg_text, interface_names):
        while True:
            log.debug('pulse() is about to send')
            if interface_names:
                for interface_name in interface_names:
                    cp.l3_send_text(msg_text, dst_ip, src_ip, specified_interface_name=interface_name)
            else:
                cp.l3_send_text(msg_text, dst_ip, src_ip)
            log.debug(f'pulse() sent to {dst_ip}.  Pulse() is about to sleep')
            await asyncio.sleep(pulse_interval)

    log.debug('Creating pulsar task')
    loop.create_task(
        pulse(3, message, interface_names)
    )

    with utils.LoopExceptionHandler(loop):
        loop.run_forever()
