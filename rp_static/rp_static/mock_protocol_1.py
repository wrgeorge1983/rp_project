"""mock_protocol_1.py
defines Mock Protocol 1.0"""
import logging
import asyncio

import yaml
from rp_static.generic_l2 import TransportInstance, TransportInstanceCollection, get_mq_channel, \
    config_instances_from_state, transport_instances
from rp_static.messages import TransportMessage

from rp_static.utils import get_configs, LoopExceptionHandler, _loop_timeout

log = logging.getLogger(__name__)


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


    async def cb_message_echoer(self, msg: TransportMessage):
        loop = self.loop
        for instance in self.transport_instances:
            loop.create_task(instance.send(msg.content))

    async def cb_timeout(self, n, f):
        await asyncio.sleep(n)
        self.timer_running = False
        await f

    def cb_message_handler(self, msg: TransportMessage):
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
