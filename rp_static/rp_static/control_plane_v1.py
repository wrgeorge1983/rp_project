"""control_plane_v1.py
defines first version of control plane implementation"""

import asyncio
import logging
log = logging.getLogger(__name__)

import yaml

from rp_static import generic_l2 as l2
from rp_static import utils


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
    return transport_instances

def start_cp(state):
    log.debug('entering start_cp()')
    loop = asyncio.get_event_loop()
    if state.ext_debug:
        loop.set_debug(enabled=True)

    with utils.LoopExceptionHandler(loop):
        transport_intances = loop.run_until_complete(config_instances_from_state(state, loop))




