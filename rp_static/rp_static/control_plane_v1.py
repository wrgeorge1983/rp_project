"""control_plane_v1.py
defines first version of control plane implementation"""

import asyncio
from ipaddress import ip_network, ip_interface, ip_address, \
    IPv4Address, IPv4Network, IPv4Interface, IPv6Address, IPv6Network, IPv6Interface
import logging
log = logging.getLogger(__name__)
from pprint import pformat, pprint
from typing import Union, Sequence, Dict

import yaml

from rp_static import generic_l2 as l2
from rp_static import utils

GLOBAL_STATE = {
    'strict_config_handling': True
}


class FIBValue:
    def __init__(self, fib_id):
        self.fib_id = fib_id

    def __eq__(self, other):
        try:
            return self.fib_id == other.fib_id
        except AttributeError:
            return self.fib_id == other

    def __str__(self):
        return str(self.fib_id)

    def __repr__(self):
        return f'{self.__class__.__name__}(\'{self.fib_id}\')'


class FIBEgressInterface(FIBValue):
    def __init__(self, name):
        super().__init__(name)
        self.name = name


class FIBNextHop(FIBValue):
    def __init__(self, address):
        super().__init__(str(address))
        self.ip = self.address = address


class FIB:
    def __init__(self):
        self.destinations = {}
        # self.destinations = {
        #     IPv4Network('10.0.1.0/24'): FIBEgressInterface('E0'),
        #     IPv4Network('0.0.0.0/0'): FIBEgressInterface('Null0'),
        #     IPv4Network('0::0/0'): FIBEgressInterface('Null0'),
        #     # IPv4Network('10.0.1.0/24'): FIBEgressInterface('E1'),
        #     IPv4Network('10.1.8.0/24'): FIBNextHop('10.0.1.3')
        # }

    def lookup(self, lookup_address, recursive=False):
        longest_match: Union[None, IPv4Network] = None
        for dest in self.destinations:
            if lookup_address in dest:
                if (longest_match is None) or (dest.prefixlen > longest_match.prefixlen):
                    longest_match = dest
        try:
            result = self.destinations[longest_match]
            if recursive and not isinstance(result, FIBEgressInterface):
                result = self.lookup(result.address, recursive=True)
            return result
        except KeyError:
            raise ValueError(f'Unable to find {lookup_address} in FIB')

    def add_entry(self, destination, value):
        if not isinstance(value, FIBValue):
            raise NotImplementedError(f'Can only add FIB values of type FIBValue, not {type(value)} like {value}')

        if not isinstance(destination, (IPv6Network, IPv4Network)):
            raise NotImplementedError(f'Can only add FIB destinations as IP Networks, not {type(destination)} like {destination}')

        self.destinations[destination] = value

    def add_entries_from_interface_configs(self, interface_configs):
        """FIB.add_entries_from_interface_configs()
        Add FIB entries for connected interfaces"""
        for interface in interface_configs:
            destination = interface['config']['ipaddr'].network
            fib_value = FIBEgressInterface(interface['name'])
            log.debug(f'adding FIB entry for {interface["name"]} using config: {interface["config"]}')
            self.add_entry(destination, fib_value)

    def __str__(self):
        return pformat(self.destinations, width=-1)

    def __repr__(self):
        return f'{self.__class__.__name__}({str(self)})'


class ForwardingPlane:
    def __init__(self):
        self.fib = FIB()
        self.interfaces = []
        self.loop: asyncio.BaseEventLoop = None
        self.tic: l2.TransportInstanceCollection = None

    async def async_init(self, topology_config, state, loop):
        self.loop = loop
        await self.process_config(topology_config, state, loop)

    def add_fib_entry(self, dest, value):
        self.fib.add_entry(dest, value)

    def add_fib_entries_from_interface_configs(self):
        self.fib.add_entries_from_interface_configs(self.interfaces)

    def fib_lookup(self, lookup_address, recursive=False):
        return self.fib.lookup(lookup_address, recursive)

    def send(self, msg, logical_interface_name):
        instance = self.tic.get_instance_by_interface_name(logical_interface_name)
        self.loop.create_task(instance.send(msg))

    async def process_config(self, topology_config, state, loop):
        self.tic = await self.config_rmq_instances_from_state(state, topology_config, loop)

    @staticmethod
    async def config_rmq_instances_from_state(state, topology_config, loop):
        log.debug('entered ForwardingPlane.config_instances_from_state()')
        channel, connection = await l2.get_mq_channel(topology_config, loop=loop)
        hostname = state.hostname
        my_topo = topology_config.get(hostname, {})
        if not my_topo:
            log.warning(f'No topology definition found for hostname {hostname}')
            # TODO: Do something smarter with this
            raise NotImplementedError('I plan to do something smarter with this, but haven\'t yet')

        transport_instances = l2.TransportInstanceCollection()

        for interface, network_name in my_topo['interfaces'].items():
            instance = l2.TransportInstance(
                logical_interface=interface,
                network_name=network_name,
                rmq_channel=channel,
                rmq_connection=connection,
                hostname=hostname
            )
            await instance.async_init()
            log.debug('completed async_init()')
            transport_instances.add_instance(instance)
        return transport_instances

    # def _register_listener_callback(self, cb, pattern, logical_interface:str):
    #     transport_instance = self.tic.get_instance_by_interface_name(logical_interface)
    #
    #     def _cb(message):
    #         log.debug(f'ForwardingPlane.listener_callback() processing message: {message}')
    #         if self.kv_pattern_matcher(message, pattern):
    #             # log.debug(f'message matched pattern: {pattern}')
    #             cb(message)
    #
    #     self.loop.create_task(transport_instance.recv_w_callback(_cb))
    #
    # @staticmethod
    # def kv_pattern_matcher(message:l2.TransportMessage, pattern:dict) -> bool:
    #     log.debug('Entering ForwardingPlane.kv_pattern_matcher')
    #
    #     for key, value in pattern.items():
    #         if getattr(message, key, None) != value:
    #             log.debug('message did not match pattern')
    #             return False
    #     log.debug('message matched pattern')
    #     return True

    @staticmethod
    def _interface_listener_filter_callback(inner_cb, msg_filter):
        log.debug('entering ForwardingPlane._interface_listener_filter_callback()')

        def _cb(message):
            log.debug('executing ForwardingPlane listener filter closure')
            if msg_filter(message):
                log.debug('message matched filter')
                inner_cb(message)
            else:
                log.debug('message did not match filter')
        return _cb

    def register_interface_listener(self, cb, logical_interface_name:str, msg_filter=None):
        log.debug('entering ForwardingPlane.register_interface_listener()')
        transport_instance = self.tic.get_instance_by_interface_name(logical_interface_name)

        if msg_filter is None:
            msg_filter = lambda x: True

        cb = self._interface_listener_filter_callback(cb, msg_filter)

        self.loop.create_task(transport_instance.recv_w_callback(cb))


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

    def send_text(self, msg_text, interface_names: Sequence[str] = None):
        if interface_names is None:  # None == "all"
            interface_names = self.interface_names

        for interface_name in interface_names:
            self.fp.send(msg_text, interface_name)


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
            cp.send_text(msg_text, interface_names=interface_names)
            log.debug('pulse() sent')

    log.debug('Creating pulsar task')
    loop.create_task(
        pulse(3, message, ('E0', 'E2'))
    )

    with utils.LoopExceptionHandler(loop):
        loop.run_forever()


