""""messages.py
defines messages for use in Forwarding Plane"""
import json


class BaseMessage:
    _serializable_attributes = tuple()

    @property
    def as_json(self) -> str:
        r_dict = {key: val for key, val in self.__dict__.items()
                  if (key in self._serializable_attributes and val is not None)}
        return json.dumps(r_dict)

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

    def __init__(self, content, source_host=None, egress_interface=None, network_segment=None, src_mac=None, dst_mac=None):
        self.content = content
        self.source_host = source_host
        self.egress_interface = egress_interface
        self.ingress_interface = None
        self.network_segment = network_segment
        self.src_mac = src_mac
        self.dst_mac = dst_mac


class NetworkMessage(BaseMessage):
    _serializable_attributes = (
        'content'
    )

    def __init__(self, content):
        self.content = content
