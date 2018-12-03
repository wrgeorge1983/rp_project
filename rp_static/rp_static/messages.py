""""messages.py
defines messages for use in Forwarding Plane"""
import json
from ipaddress import ip_network, ip_interface, ip_address
from ipaddress import IPv4Network, IPv6Network, IPv4Interface, IPv6Interface, IPv4Address, IPv6Address
import ipaddress
from typing import Union, Dict, Sequence, List

from rp_static.utils import IPAddressType


class MessageSerializer(json.JSONEncoder):
    @staticmethod
    def serialize_ip_addresses(obj:ipaddress._BaseAddress):
        return str(obj)

    def default(self, obj):
        if isinstance(obj, ipaddress._BaseAddress):
            return self.serialize_ip_addresses(obj)
        return super().default(obj)


class BaseMessage:
    _serializable_attributes = tuple()

    @property
    def as_dict(self) -> dict:
        r_dict = {key: val for key, val in self.__dict__.items()
                  if (key in self._serializable_attributes and val is not None)}
        return r_dict

    @property
    def as_json(self) -> str:
        return json.dumps(self.as_dict, cls=MessageSerializer)

    def __str__(self):
        return self.as_json


class TransportMessage(BaseMessage):
    _serializable_attributes = (
        'content',
        'source_host',
        'src_mac',
        'dst_mac',
        'egress_interface',
        'ingress_interface',
        'network_segment'
    )

    def __init__(self, content, source_host=None, egress_interface=None,
                 network_segment=None, src_mac=None, dst_mac=None):
        self.content = content
        self.source_host = source_host
        self.egress_interface = egress_interface
        self.ingress_interface = None
        self.network_segment = network_segment
        self.src_mac = src_mac
        self.dst_mac = dst_mac


class NetworkMessage(BaseMessage):
    _serializable_attributes = (
        'content',
        'dest_ip',
        'src_ip',
        'egress_interface',
        'proto_number'
    )

    def __init__(self, content, dest_ip: IPAddressType, egress_interface_name=None,
                 src_ip: IPAddressType=None, proto_number=0):
        self.content = content
        self.dest_ip = dest_ip
        self.src_ip = src_ip
        self.egress_interface_name = egress_interface_name
        self.proto_number = proto_number
