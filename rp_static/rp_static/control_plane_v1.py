"""control_plane_v1.py
defines first version of control plane implementation"""

import asyncio
from ipaddress import ip_network, ip_interface, ip_address, \
    IPv4Address, IPv4Network, IPv4Interface, IPv6Address, IPv6Network, IPv6Interface
import logging
log = logging.getLogger(__name__)
from pprint import pformat, pprint
from typing import Union, Sequence

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

    def lookup(self, lookup_address):
        longest_match: Union[None, IPv4Network] = None
        for dest in self.destinations:
            if lookup_address in dest:
                if (longest_match is None) or (dest.prefixlen > longest_match.prefixlen):
                    longest_match = dest
        try:
            return self.destinations[longest_match]
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


class ControlPlane:
    def __init__(self):
        self._fib = FIB()
        self.interfaces = []

    async def async_init(self, state, loop):
        log.debug('entering ControlPlane.async_init()')
        self.loop = loop

        tic, router_config = await config_instances_from_state(state, loop)
        self.transport_instance_collection = tic
        self.process_config(router_config)

    def process_config(self, config):
        self.config = config
        self.interfaces = [
            {'name': key, 'config': self.process_interface_config(key, value)}
             for key, value in config['interfaces'].items()
        ]
        self._fib.add_entries_from_interface_configs(self.interfaces)


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




async def config_instances_from_state(state, loop):
    log.debug('entered config_instances_from_state()')
    configs = utils.get_configs_by_hostname(state.config_file_path,
                                            state.topology_file,
                                            state.hostname)
    log.debug('configs collected')
    channel, connection = await l2.get_mq_channel(configs, loop=loop)
    topology = configs['topology']
    # router_config = configs['router_config']
    hostname = state.hostname
    my_topo = topology.get(hostname, {})
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
    return transport_instances, configs['router_config']

def start_cp(state):
    log.debug('entering start_cp()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    cp = ControlPlane()

    with utils.LoopExceptionHandler(loop):
        loop.run_until_complete(cp.async_init(state, loop))

    log.info(f'Created fib: {repr(cp._fib)}')

    test_destinations = [
        '192.168.1.1',
        '10.0.1.1',
        '10.0.0.0',
        '10.0.1.8'
    ]

    for dest in test_destinations:
        dest_addr = ip_address(dest)
        try:
            result = cp._fib.lookup(dest_addr)
        except ValueError:
            result = 'NOT FOUND'
        log.info(f'looking up {dest} in fib: {repr(result)}')





