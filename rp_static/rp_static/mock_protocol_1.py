"""mock_protocol_1.py
defines Mock Protocol 1.0"""
import logging
from typing import List, Type, Dict, Union
from contextlib import suppress
import asyncio

import yaml
import aio_pika, aio_pika.exceptions
# import pika, pika.exceptions

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


class TransportInstance:
    def __init__(self, rmq_channel, rmq_connection, network_name, logical_interface):
        self.rmq_channel:aio_pika.Channel = rmq_channel
        self.rmq_connection = rmq_connection
        self.network_name = network_name
        self.exchange_name = f'net_{network_name}'
        self.logical_interface = logical_interface

    async def async_init(self,):
        await self._rmq_init()

    async def _rmq_init(self):
        log.debug(f'entering _rmq_init for {self.network_name}:{self.logical_interface}')
        log.debug(f'declaring exchange for {self.network_name}:{self.logical_interface}')
        self.exchange = exchange = await self.rmq_channel.declare_exchange(
            name=self.exchange_name,
            type=aio_pika.ExchangeType.FANOUT
        )

        log.debug(f'declaring queue for {self.network_name}:{self.logical_interface}')
        self.queue = queue = await self.rmq_channel.declare_queue(exclusive=True)
        self.queue_name = queue_name = queue.name

        log.debug(f'binding queue for {self.network_name}:{self.logical_interface}')
        await queue.bind(exchange=exchange)
        # await self.rmq_channel.bind_(
        #     exchange=self.exchange_name,
        #     queue = queue_name
        # )

    async def _pub(self, msg):
        log.debug(f'publishing message {msg} on {self.network_name}:{self.logical_interface}')
        message = aio_pika.Message(body=msg)
        await self.exchange.publish(message,routing_key='')
        # await self.rmq_channel.basic_publish(
        #     exchange=self.exchange_name,
        #     routing_key='',
        #     body=msg
        # )

    def queue_callback(self, message: aio_pika.IncomingMessage):
        # with message.process():
        log.info(f'Received {message.body}')

    # def queue_callback(self, ch, method, properties, body):
    #     log.info(f'Received {body.decode()}')

    async def _sub(self):
        def _queue_callback(*args, **kwargs):
            self.queue_callback(*args, **kwargs)

        # await self.rmq_channel.basic_consume(
        #     _queue_callback,
        #     queue=self.queue_name,
        #     no_ack=True
        # )

        log.info(f'Waiting for messages forever on {self.network_name}:{self.logical_interface}.  To exit press CTRL-C???')
        await self.queue.consume(
            callback=_queue_callback,
            no_ack=True,
        )
        log.info(f'Done consuming on {self.network_name}:{self.logical_interface}')
        # await self.rmq_channel.start_consuming()

    async def send(self, msg):
        await self._pub(msg)

    async def recv(self):
        await self._sub()

    async def close(self):
        """
        Closes the associated channel and connection.  Gracefully handles channels and connections that have already
        been closed.
        :return:
        """
        # with suppress()
        log.debug(f'Shutting down TransportInstance for {self.network_name}:{self.logical_interface}')
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
            raise ValueError(f'Can\'t add instance for {instance.network_name}:{instance.logical_interface} '
                             f'to TransportInstanceCollection because it already exists.' )
        log.debug(f'Adding instance for {instance.network_name}:{instance.logical_interface} to TransportInstanceCollection')
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
            rmq_connection=connection
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


async def _timeout(n, loop):
    await asyncio.sleep(n, loop=loop)
    loop.stop()


def start_actor(state, timeout):

    log.debug('entering start_actor()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    log.debug('event loop created, configuring instances')
    with LoopExceptionHandler(loop):
        loop.run_until_complete(config_instances_from_state(state, loop))

    log.debug('instances configured, creating receive tasks')

    for instance in transport_instances:
        loop.create_task(instance.recv())
    log.debug('receive tasks created')

    if timeout:
        log.debug(f'adding timeout of {timeout} seconds')
        loop.create_task(_timeout(timeout, loop))

    with LoopExceptionHandler(loop):
        log.debug('running loop forever!')
        loop.run_forever()
        log.debug('running ceased')


def start_initiator(state, msg: str, timeout):

    log.debug('entering start_actor()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    log.debug('event loop created, configuring instances')
    with LoopExceptionHandler(loop):
        loop.run_until_complete(config_instances_from_state(state, loop))

    log.debug('instances configured, creating receive tasks')

    for instance in transport_instances:
        loop.create_task(instance.send(msg.encode()))
        # loop.create_task(instance.recv())
    log.debug('receive tasks created')

    if timeout:
        log.debug(f'adding timeout of {timeout} seconds')
        loop.create_task(_timeout(timeout, loop))

    with LoopExceptionHandler(loop):
        log.debug('running loop forever!')
        loop.run_forever()
        log.debug('running ceased')
