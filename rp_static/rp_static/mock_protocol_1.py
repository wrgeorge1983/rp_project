"""mock_protocol_1.py
defines Mock Protocol 1.0"""
import logging
import json
from typing import List, Type, Dict, Union
from contextlib import suppress
from functools import partial
import asyncio

import yaml
import aio_pika, aio_pika.exceptions

from rp_static.utils import get_configs

log = logging.getLogger(__name__)


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


class TransportMessage:
    _serializable_attributes = [
        'content',
        'source_host',
        'egress_interface',
        'ingress_interface',
        'network_segment'
    ]

    def __init__(self, content, source_host=None, egress_interface=None, network_segment=None):
        self.content = content
        self.source_host = source_host
        self.egress_interface = egress_interface
        self.ingress_interface = None
        self.network_segment = network_segment

    @property
    def as_json(self) -> str:
        r_dict = {key: val for key, val in self.__dict__.items()
                  if (key in self._serializable_attributes and val is not None)}
        return json.dumps(r_dict)

    def __str__(self):
        return self.as_json


class TransportInstance:
    def __init__(self, rmq_channel, rmq_connection, network_name, logical_interface, hostname):
        self.rmq_channel:aio_pika.Channel = rmq_channel
        self.rmq_connection = rmq_connection
        self.network_name = network_name
        self.exchange_name = f'net_{network_name}'
        self.logical_interface = logical_interface
        self.hostname = hostname

    @property
    def net_int(self):
        return f'{self.network_name}:{self.logical_interface}'

    async def async_init(self,):
        await self._rmq_init()

    async def _rmq_init(self):
        log.debug(f'entering _rmq_init for {self.net_int}')
        log.debug(f'declaring exchange for {self.net_int}')
        self.exchange = exchange = await self.rmq_channel.declare_exchange(
            name=self.exchange_name,
            type=aio_pika.ExchangeType.FANOUT
        )

        log.debug(f'declaring queue for {self.net_int}')
        self.queue = queue = await self.rmq_channel.declare_queue(exclusive=True)
        self.queue_name = queue_name = queue.name

        log.debug(f'binding queue for {self.net_int}')
        await queue.bind(exchange=exchange)

    async def _pub(self, msg:TransportMessage):
        log.debug(f'publishing message {msg} on {self.net_int}')
        m_body = msg.as_json.encode()
        message = aio_pika.Message(body=m_body)
        await self.exchange.publish(message,routing_key='')

    @staticmethod
    def queue_callback(message: aio_pika.IncomingMessage, *args, **kwargs):
        log.info(f'Received {message.body.decode()}')

    async def _sub_w_callback(self, callback):
        log.debug(f'Beginning to consume for {self.net_int}')
        await self.queue.consume(
            callback=callback,
            no_ack=True,
        )
        log.info(f'started consuming on {self.net_int}')

    def egress_format_message(self, msg: Union[str, dict, TransportMessage]) -> TransportMessage:
        if isinstance(msg, TransportMessage):
            pub_message = msg
        elif isinstance(msg, (dict, str)):
            pub_message = TransportMessage(content=msg)
        else:
            raise NotImplementedError(f'send() only works on types str, TransportMessage, or dict.  Not {type(msg)}')

        pub_message.egress_interface = self.logical_interface
        pub_message.source_host = self.hostname
        pub_message.network_segment = self.network_name
        return pub_message

    def ingress_format_message(self, i_msg: aio_pika.IncomingMessage) -> Union[TransportMessage, None]:
        m_body = json.loads(i_msg.body)
        msg = TransportMessage(**m_body)
        if msg.egress_interface == self.logical_interface:
            return
        msg.ingress_interface = self.logical_interface
        return msg

    async def send(self, msg:Union[str, TransportMessage, dict]):
        pub_message = self.egress_format_message(msg)
        await self._pub(pub_message)

    async def recv_w_callback(self, callback=None):
        if callback is None:
            log.debug('None callback used')
            callback = self.queue_callback

        def _callback(message):
            message = self.ingress_format_message(message)
            if message is not None:
                callback(message)

        await self._sub_w_callback(_callback)

    async def close(self):
        """
        Closes the associated channel and connection.  Gracefully handles channels and connections that have already
        been closed.
        :return:
        """
        log.debug(f'Shutting down TransportInstance for {self.net_int}')
        log.debug(f'Closing RabbitMQ channel')

        with suppress(aio_pika.exceptions.ChannelClosed):
            await self.rmq_channel.close()
        with suppress(aio_pika.exceptions.ConnectionClosed):
            await self.rmq_connection.close()


class TransportInstanceCollection:
    def __init__(self):
        self._instances_by_interfaces: Dict[str, TransportInstance] = dict()
        self._instances: List[TransportInstance] = []

    def add_instance(self, instance:TransportInstance):
        if not isinstance(instance, TransportInstance):
            raise ValueError(f'TransportInstanceManager can only managed TransportInstances, not {type(instance)}s!')
        if instance in self._instances or instance.logical_interface in self._instances_by_interfaces:
            raise ValueError(f'Can\'t add instance for {instance.net_int} '
                             f'to TransportInstanceCollection because it already exists.' )
        log.debug(f'Adding instance for {instance.net_int} to TransportInstanceCollection')
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

    async def close(self):
        log.debug('Shutting down transport instances.')
        for instance in self._instances:
            await instance.close()

    def __iter__(self):
        return iter(self._instances)


transport_instances = TransportInstanceCollection()


async def get_mq_channel(config, loop) -> (aio_pika.Channel, aio_pika.Connection):
    log.debug('entered get_mq_channel()')
    mt_config = config['topology']['message_transport']
    if not mt_config['type'] == 'rabbitmq':
        raise ValueError('rmq pub/sub commands must be used with a message '
                         'transport type of "rabbitmq", not {mt_config["type"]}')
    rmq_host = mt_config['hostname']
    log.info(f'Using {rmq_host} as rabbitMQ host')

    connection = await aio_pika.connect(
        f'amqp://guest:guest@{rmq_host}/', loop=loop
    )

    channel = await connection.channel()
    return channel, connection


async def config_instances_from_state(state, loop):
    log.debug('entered config_instances_from_state()')
    configs = get_configs(None, state.topology_file)
    log.debug('configs collected')
    channel, connection = await get_mq_channel(configs, loop=loop)
    topology = configs['topology']
    # router_config = configs['router_config']
    hostname = state.hostname
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
            rmq_connection=connection,
            hostname=hostname
        )
        await instance.async_init()
        log.debug('completed async_init()')
        transport_instances.add_instance(instance)


# async def work_from_state(state, loop):
#     log.debug('entered config_instances_from_state()')
#     configs = get_configs(None, state.topology_file)
#     log.debug('configs collected')
#     channel, connection = await get_mq_channel(configs, loop=loop)
#     topology = configs['topology']
#     # router_config = configs['router_config']
#     hostname = state.hostname
#     my_topo = topology.get(hostname, {})
#     if not my_topo:
#         log.warning(f'No topology definition found for hostname {hostname}')
#         # TODO: Do something smarter with this
#         raise NotImplementedError('I plan to do something smarter with this, but haven\'t yet')
#
#     for interface, network_name in my_topo['interfaces'].items():
#         instance = TransportInstance(
#             logical_interface=interface,
#             network_name=network_name,
#             rmq_channel=channel,
#             rmq_connection=connection
#         )
#         await instance.async_init()
#         log.debug('completed async_init() for {instance.network_name}:{instance.logical_interface}.')
#         transport_instances.add_instance(instance)
#
#     for instance in transport_instances._instances:
#         log.debug('calling recv() for {instance.network_name}:{instance.logical_interface}.')
#         await instance.recv()


async def _loop_timeout(n, loop):
    await asyncio.sleep(n, loop=loop)
    loop.stop()


class MPActor:
    def __init__(self):
        self.timer_running = False
        self.transport_instances = TransportInstanceCollection()
        # self.loop = asyncio.get_event_loop()

    async def async_init(self, state, loop):
        log.debug('entering MPActor.async_init()')
        self.loop = loop
        self.configs = configs = get_configs(None, state.topology_file)
        log.debug('configs collected')

        channel, connection = await get_mq_channel(configs, loop=loop)
        topology = configs['topology']

        self.hostname = hostname = state.hostname
        my_topo = topology.get(hostname, {})
        if not my_topo:
            log.warning(f'No topology definition found for hostname {hostname}')
            raise NotImplementedError('I don\'t know if anything else can or should be done with this')

        transport_instances = self.transport_instances

        for interface, network_name in my_topo['interfaces'].items():
            instance = TransportInstance(
                logical_interface=interface,
                network_name=network_name,
                rmq_channel=channel,
                rmq_connection=connection,
                hostname=hostname
            )
            await instance.async_init()
            log.debug(f'completed async_init() for {interface}')
            transport_instances.add_instance(instance)


    async def cb_message_echoer(self, msg:TransportMessage):
        loop = self.loop
        for instance in self.transport_instances:
            loop.create_task(instance.send(msg.content))

    async def cb_timeout(self, n, f):
        await asyncio.sleep(n)
        self.timer_running = False
        await f

    def cb_message_handler(self, msg:TransportMessage):
        if self.timer_running:
            log.debug('Message discarded due to running timer')
            return

        log.info('Actor received message')
        log.debug(f'{yaml.dump(msg)}')

        self.timer_running = True
        self.loop.create_task(self.cb_timeout(5, self.cb_message_echoer(msg)))

    def create_receive_tasks(self):
        log.debug('entering MPActor.create_receive_tasks()')
        loop = self.loop
        cb_message_handler = self.cb_message_handler
        for instance in self.transport_instances:
            loop.create_task(instance.recv_w_callback(cb_message_handler))


def start_actor_v1(state, timeout):
    log.debug('entering start_actor_v1()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)
    log.info('event loop created, configuring instances')

    actor = MPActor()
    with LoopExceptionHandler(loop):
        loop.run_until_complete(actor.async_init(state, loop))
    log.info('instances configured, creating receive tasks')

    actor.create_receive_tasks()
    log.info('receive tasks created')

    if timeout:
        log.debug(f'adding timeout of {timeout} seconds')
        loop.create_task(_loop_timeout(timeout, loop))

    with LoopExceptionHandler(loop):
        log.debug('running loop forever (unless/until timeout)!')
        loop.run_forever()
        log.debug('loop is over!')


def start_initiator(state, msg: str, timeout, interface):

    log.debug('entering start_actor()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    log.debug('event loop created, configuring instances')
    with LoopExceptionHandler(loop):
        loop.run_until_complete(config_instances_from_state(state, loop))

    log.debug('instances configured, creating receive tasks')

    if interface is None:
        instances = transport_instances
    else:
        instances = [
            instance for instance in transport_instances
            if instance.logical_interface == interface
        ]

    for instance in instances:
        loop.create_task(instance.send(msg))

    log.debug('receive tasks created')

    if timeout:
        log.debug(f'adding timeout of {timeout} seconds')
        loop.create_task(_loop_timeout(timeout, loop))

    with LoopExceptionHandler(loop):
        log.debug('running loop forever!')
        loop.run_forever()
        log.debug('running ceased')
