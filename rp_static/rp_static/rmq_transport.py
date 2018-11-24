"""rmq_transport.py
define RabbitMQ based transport"""
import logging
from typing import List, Type, Dict
from contextlib import suppress

import yaml
import pika, pika.exceptions

from rp_static.utils import get_configs

log = logging.getLogger(__name__)


class TransportInstance():
    def __init__(self, rmq_channel, rmq_connection, network_name, logical_interface):
        self.rmq_channel = rmq_channel
        self.rmq_connection = rmq_connection
        self.network_name = network_name
        self.exchange_name = f'net_{network_name}'
        self.logical_interface = logical_interface
        self._rmq_init()

    def _rmq_init(self):
        log.debug(f'entering _rmq_init for {self.network_name}')
        log.debug(f'declaring exchange for {self.network_name}')
        self.rmq_channel.exchange_declare(
            exchange=self.exchange_name,
            exchange_type='fanout'
        )

        log.debug(f'declaring queue for {self.network_name}')
        self.queue = queue = self.rmq_channel.queue_declare(exclusive=True)
        self.queue_name = queue_name = queue.method.queue

        log.debug(f'binding queue for {self.network_name}')
        self.rmq_channel.queue_bind(
            exchange=self.exchange_name,
            queue = queue_name
        )

    def _pub(self, msg):
        self.rmq_channel.basic_publish(
            exchange=self.exchange_name,
            routing_key='',
            body=msg
        )

    def queue_callback(self, ch, method, properties, body):
        log.info(f'Received {body.decode()}')

    def _sub(self):
        def _queue_callback(*args, **kwargs):
            self.queue_callback(*args, **kwargs)

        self.rmq_channel.basic_consume(
            _queue_callback,
            queue=self.queue_name,
            no_ack=True
        )

        log.info(f'Waiting for messages forever on {self.network_name}.  To exit press CTRL-C')
        self.rmq_channel.start_consuming()

    def send(self, msg):
        self._pub(msg)

    def recv(self):
        self._sub()

    def close(self):
        """
        Closes the associated channel and connection.  Gracefully handles channels and connections that have already
        been closed.
        :return:
        """
        # with suppress()
        log.debug(f'Shutting down TransportInstance for {self.network_name}')
        log.debug(f'Closing RabbitMQ channel')

        with suppress(pika.exceptions.ChannelClosed):
            self.rmq_channel.close()
        with suppress(pika.exceptions.ConnectionClosed):
            self.rmq_connection.close()


class TransportInstanceCollection():
    def __init__(self):
        self._instances_by_interfaces: Dict[str, TransportInstance] = dict()
        self._instances: List[TransportInstance] = []

    def add_instance(self, instance:TransportInstance):
        if not isinstance(instance, TransportInstance):
            raise ValueError(f'TransportInstanceManager can only managed TransportInstances, not {type(instance)}s!')
        if instance in self._instances or instance.logical_interface in self._instances_by_interfaces:
            raise ValueError(f'Can\'t add instance with network_name of {instance.network_name} and logical_interface '
                             f'of {instance.logical_interface} to TransportInstanceCollection because it already exists.' )
        self._instances_by_interfaces[instance.logical_interface] = instance
        self._instances.append(instance)

    def get_instance_by_interface_name(self, interface_name) -> TransportInstance:
        """
        :param interface_name: the interface name to search on.
        :return: a SINGLE instance associated with that interface name, if any exists.  Raises KeyError otherwise.
        """
        return self._instances_by_interfaces[interface_name]

    def get_instances_by_network_name(self, network_name) -> List[TransportInstance]:
        """
        :param network_name: the network name to search on.
        :return: a LIST of any TransportInstance objects associated with that network_name
        """
        rslt = [
            instance for instance in self._instances_by_interfaces.values()
            if instance.network_name == network_name
        ]

        return rslt

    def close(self):
        log.debug('Shutting down transport instances.')
        for instance in self._instances:
            instance.close()


transport_instances = TransportInstanceCollection()


def config_instances_from_state(state):
    configs = get_configs(state.config_file, state.topology_file)
    channel, connection = get_mq_channel(configs)
    topology = configs['topology']
    router_config = configs['router_config']
    hostname = router_config['hostname']
    my_topo = topology.get(hostname, {})
    if not my_topo:
        log.warning(f'No topology definition found for hostname {hostname}')
        # TODO: Do something smarter with this
        raise NotImplementedError('I plan to do something smarter with this, but haven\'t yet')

    for interface, network_name in my_topo['interfaces'].items():
        instance = TransportInstance(
            logical_interface=interface,
            network_name=network_name,
            rmq_channel=channel,
            rmq_connection=connection
        )
        transport_instances.add_instance(instance)


def get_mq_channel(config):
    mt_config = config['topology']['message_transport']
    if not mt_config['type'] == 'rabbitmq':
        raise ValueError('rmq pub/sub commands must be used with a message '
                         'transport type of "rabbitmq", not {mt_config["type"]}')
    rmq_host = mt_config['hostname']
    log.info(f'Using {rmq_host} as rabbitMQ host')

    connection:pika.BlockingConnection = pika.BlockingConnection(pika.ConnectionParameters(rmq_host))
    channel = connection.channel()
    return channel, connection


def test_rmq_pub(state, msg, network_name=None, interface_name=None):
    if network_name is None and interface_name is None:
        raise ValueError('Must specify either network_name or instance_name')

    config_instances_from_state(state)
    if network_name:
        instances = transport_instances.get_instances_by_network_name(network_name)
    else:
        instance = transport_instances.get_instance_by_interface_name(interface_name)
        instances = [instance]

    for instance in instances:
        instance.send(msg)
        log.info(f'Sent {msg} on {instance.network_name}')

    transport_instances.close()


def test_rmq_sub(state, interface_name):
    config_instances_from_state(state)
    instance = transport_instances.get_instance_by_interface_name(interface_name)

    try:
        instance.recv()
    except KeyboardInterrupt as e:
        log.debug('KeyboardInterrupt caught, closing rmq resources')
        transport_instances.close()
        raise e

    log.debug('KeyboardInterrupt not caught, closing rmq resources anyway')
    transport_instances.close()
