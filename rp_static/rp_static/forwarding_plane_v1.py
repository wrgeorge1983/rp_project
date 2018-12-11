"""forwarding_plane_v1.py
defines first version of forwarding plane implementation"""
import asyncio
from ipaddress import IPv4Network, IPv6Network, ip_address
import logging
log = logging.getLogger(__name__)
from pprint import pformat
from typing import Union, List, Tuple, Set

from rp_static import generic_l2 as l2
from rp_static.messages import TransportMessage, NetworkMessage
from rp_static.utils import IPAddressType

class FIBValue:
    def __init__(self, fib_id):
        self.fib_id = fib_id

    def __eq__(self, other):
        try:
            return self.fib_id == other.fib_id
        except AttributeError:
            return self.fib_id == other

    def __hash__(self):
        return hash(self.fib_id)

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
        self.fib_values: Set[FIBValue] = set()

    def lookup(self, lookup_address: IPAddressType, recursive=False) -> Tuple[Union[FIBNextHop, FIBEgressInterface], IPv4Network]:
        log.debug(f'FIB.lookup(): looking up {lookup_address} in FIB')
        longest_match: Union[None, IPv4Network] = None
        for dest in self.destinations:
            log.debug(f'FIB.Lookup(): checking {dest}')
            if lookup_address in dest:
                if (longest_match is None) or (dest.prefixlen > longest_match.prefixlen):
                    longest_match = dest
        try:
            result = self.destinations[longest_match]
            if recursive and not isinstance(result, FIBEgressInterface):
                result, longest_match = self.lookup(result.address, recursive=True)
            log.debug(f'FIB.lookup(): got {result}')
            return result, longest_match
        except KeyError:
            log.debug(f'FIB.lookup(): no result!')
            raise ValueError(f'Unable to find {lookup_address} in FIB')

    def lookup_by_name(self, name):
        for value in self.fib_values:
            if value.fib_id == name:
                return value
        log.debug(f'FIB lookup failed looking for {name} in {self.fib_values}')
        raise ValueError(f'FIB.lookup_by_name() Couldn\'t find {name} in the FIB!')

    def add_entry(self, destination, value):
        if not isinstance(value, FIBValue):
            raise NotImplementedError(f'Can only add FIB values of type FIBValue, not {type(value)} like {value}')

        if not isinstance(destination, (IPv6Network, IPv4Network)):
            raise NotImplementedError(f'Can only add FIB destinations as IP Networks, not {type(destination)} like {destination}')

        self.destinations[destination] = value
        self.fib_values.add(value)

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
        self.hostname = state.hostname
        await self.process_config(topology_config, state, loop)

    def add_fib_entry(self, dest, value):
        self.fib.add_entry(dest, value)

    def process_interface_configs(self, interface_configs: List[dict]):
        # interface_configs are dicts file like this, derived from a config.yml:
        # {
        #     'name': 'E0',
        #     'config': {
        #         'ipaddr': IPv4Interface('10.0.1.1/24')
        #     }
        # }

        for ic in interface_configs:
            try:
                interface_mac = f'{self.tic.get_instance_by_interface_name(ic["name"]).network_name}:{ic["name"]}'
            except KeyError:
                interface_mac = f'XX:{ic["name"]}'
                log.error(f'Looking up the interface_name in the TIC failed!, falling back to dummy value of {interface_mac}')
            ic['config']['interface_mac'] = interface_mac
            self.interfaces.append(ic)

        self.add_fib_entries_from_interface_configs()

    def lookup_interface_config_by_name(self, name):
        try:
            return [ic for ic in self.interfaces if ic['name'] == name][0]
        except IndexError:
            raise ValueError(f'ForwardingPlane.lookup_interface_config_by_name() Couldn\'t find {name}')

    def add_fib_entries_from_interface_configs(self):
        # This shouldn't ever be called more than once until/unless we add some logic around deduplication
        # The hint is that we're "adding", but we're passing *all* of the interfaces each time
        self.fib.add_entries_from_interface_configs(self.interfaces)

    def fib_lookup(self, lookup_address, recursive=False) -> Tuple[Union[FIBNextHop, FIBEgressInterface], IPv4Network]:
        return self.fib.lookup(lookup_address, recursive)

    def fib_lookup_validate(self, lookup_address:IPAddressType, candidate:str):
        log.debug(f'ForwardingPlane.fib_lookup_validate(): checking {lookup_address} against {candidate}')
        try:
            egress_interface, _ = self.fib_lookup(lookup_address, recursive=True)
            valid = egress_interface.name == candidate
        except ValueError:
            valid = False
        if not valid:  # unicast lookup failed, check for BC/MC
            valid = lookup_address.is_multicast
        if not valid:
            candidate_interface = FIBEgressInterface(candidate)
            egress_networks: List[Union[IPv4Network, IPv6Network]] = [dest for dest, value
                                                                      in self.fib.destinations.items()
                                                                      if value == candidate_interface]
            valid = any(lookup_address == egress_network.broadcast_address for egress_network in egress_networks)
        if valid:
            log.debug(f'ForwardingPlane.fib_lookup_validate(): {candidate} is a valid Egress Interface for {lookup_address}')
        return valid

    def l2_send(self, msg, logical_interface_name):
        instance = self.tic.get_instance_by_interface_name(logical_interface_name)
        self.loop.create_task(instance.send(msg))

    def l3_send(self, l3_msg, specified_logical_interface_name=None):
        l2_msg = self.l2_l3_encap(l3_msg, egress_interface_name=specified_logical_interface_name, )
        self.l2_send(l2_msg, logical_interface_name=specified_logical_interface_name)

    async def process_config(self, topology_config, state, loop):
        self.tic = await self.config_rmq_instances_from_state(state, topology_config, loop)
        # self.l3_interfaces = [
        #
        # ]

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

    def l2_l3_encap_lookups(self, dst_ip: IPAddressType, src_ip: IPAddressType=None, specified_src_mac=None,
                            specified_dst_mac=None, specified_egress_interface_name=None):

        src_host = self.hostname
        dst_is_multicast = dst_ip.is_multicast

        try:
            fib_egress_interface, fib_longest_match = self.fib_lookup(dst_ip, recursive=True)
        except ValueError as e:
            if dst_is_multicast:  # it's okay that lookup failed because this is multicast
                fib_egress_interface = self.fib.lookup_by_name(specified_egress_interface_name)
                fib_longest_match = IPv4Network('224.0.0.0/4')
            else:
                raise e

        try:
            egress_interface_config = self.lookup_interface_config_by_name(fib_egress_interface.name)
        except IndexError:
            raise ValueError(f'ForwardingPlane.l2_encap_lookups() couldn\'t find {fib_egress_interface} '
                             f'in it\'s configured interfaces.')

        if src_ip is None:
            src_ip = egress_interface_config['config']['ipaddr']

        if specified_src_mac is not None:
            src_mac = specified_src_mac
        else:
            src_mac = egress_interface_config['config']['interface_mac']

        if dst_ip == ip_address('255.255.255.255'):
            dst_is_broadcast = True
        elif dst_ip == fib_longest_match.broadcast_address:
            dst_is_broadcast = True
        else:
            dst_is_broadcast = False

        if (dst_is_multicast or dst_is_broadcast) and specified_egress_interface_name is None:
            raise ValueError('Must specify egress interface for broadcast or multicast packets!')

        log.debug(f'l2_encap_lookups() found _is_broadcast and _is_multicast to be: {dst_is_broadcast, dst_is_multicast}')

        if specified_dst_mac is not None:
            dst_mac = specified_dst_mac
        elif dst_is_broadcast or dst_is_multicast:
            dst_mac = 'FF:FF:FF:FF:FF:FF'
        else:
            dst_mac = None

        return (
            src_mac,
            dst_mac,
            fib_egress_interface,
            src_host,
            src_ip
        )

    def l2_l3_encap(self, l3_message:NetworkMessage, src_mac=None, dest_mac=None, egress_interface_name=None):
        # l3_message.as_dict() = {
        #     'content': 'WE ARE HERE!',
        #     'dest_ip': '10.8.0.4',
        #     'src_ip': '10.0.1.1',
        #     'egress_interface': None,
        #     'proto_number': 8
        # }
        l2_payload = l3_message.as_dict

        src_mac, dest_mac, egress_interface, src_host, src_ip= self.l2_l3_encap_lookups(
            dst_ip=l2_payload['dest_ip'],
            src_ip=l2_payload.get('src_ip'),
            specified_src_mac=src_mac,
            specified_dst_mac=dest_mac,
            specified_egress_interface_name=egress_interface_name
        )
        l2_payload['src_ip'] = src_ip

        if egress_interface_name is None:
            try:
                egress_interface_name = egress_interface.name
            except AttributeError:
                raise ValueError(f'FIB lookup for {l3_message.dest_ip} returned {egress_interface} of type '
                                 f'{type(egress_interface)} instead of a valid FIBEgressInterface Object')

        # src_mac = src_mac if src_mac is not None else f'{self.hostname}:{egress_interface_name}'

        l2_message = TransportMessage(content=l2_payload, egress_interface=egress_interface_name,
                                      src_mac=src_mac, dst_mac=dest_mac, source_host=self.hostname)

        return l2_message

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
