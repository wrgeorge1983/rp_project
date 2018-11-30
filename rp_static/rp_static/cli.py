import logging, logging.config
import os

import click
import yaml


import rp_static.rmq_transport_test as rmq_transport_test
from rp_static.utils import get_configs
import rp_static.mock_protocol_1 as mock_protocol_1


def setup_logging():
    log_config_filename = os.environ.get('RP_LOG_CONFIG',
                                         os.path.join('configs', 'loggingconf.yml'))

    with open(log_config_filename) as infil:
        log_config = yaml.load(infil)

    logging.config.dictConfig(log_config)
    logger = logging.getLogger(__name__)
    return logger

log = setup_logging()

class State():
    def __init__(self):
        self.debug = False
        self.config_file = None
        self.topology_file = None
        self.log_debug = False
        self.ext_debug = False


pass_state = click.make_pass_decorator(State, ensure=True)  # what does 'ensure' mean here?


def option_callback(ctx, param, value):
    state = ctx.ensure_object(State)
    log.info(f'callback got param: {param.name}')
    setattr(state, param.name, value)
    # state.topology_file = value
    return value


def local_debug_option(f):
    """enables debug in our code"""
    return click.option('--debug/--no-debug',
                        expose_value=False,
                        help='Enables or disables debug mode in this project only',
                        callback=option_callback)(f)


def external_debug_option(f):
    """enables debug in external libraries"""
    return click.option('--ext-debug/--no-ext-debug',
                        expose_value=False,
                        help='Enables or disables debug mode in external libararies',
                        callback=option_callback)(f)


def log_debug(f):
    return click.option('--log-debug/--no-log-debug',
                        expose_value=False,
                        help='Enables or disables debugging of the logging configuration',
                        callback=option_callback)(f)


def config_file_option(f):
    return click.option('-c', 'config_file',
                        envvar='RP_CONFIG_FILE',
                        required=True,
                        expose_value=False,
                        type=click.File('r'),
                        callback=option_callback)(f)


def topo_file_option(f):
    return click.option('-t', 'topology_file',
                        envvar='RP_TOPOLOGY_FILE',
                        required=True,
                        expose_value=False,
                        type=click.File('r'),
                        callback=option_callback)(f)


def common_options(f):
    # f = debug_option(config_file_option(topo_file_option(log_debug(f))))
    f = local_debug_option(f)
    f = external_debug_option(f)
    f = config_file_option(f)
    f = topo_file_option(f)
    f = log_debug(f)
    return f

def common_state_ops(state):
    if state.debug:
        log.parent.setLevel(logging.DEBUG)
    if state.ext_debug:
        logging.getLogger('asyncio').setLevel(logging.DEBUG)
        logging.getLogger('aio_pika').setLevel(logging.DEBUG)
    if state.log_debug:
        import logging_tree
        logging_tree.printout()


@click.command()
@common_options
@pass_state
def main(state):
    common_state_ops(state)
    config = get_configs(state.config_file, state.topology_file)


@click.group(name='rmq')
def rmq():
    pass


@rmq.command(name='pub_test')
@common_options
@click.option('-m', 'msg', default='Hello World!!!')
@click.option('-n', 'network_name')
@click.option('-i', '--interface_name', 'interface_name')
@pass_state
def rmq_pub(state, msg, network_name, interface_name):
    common_state_ops(state)
    rmq_transport_test.test_rmq_pub(state, msg, network_name=network_name, interface_name=interface_name)


@rmq.command(name='sub_test')
@common_options
@click.option('-i', '--interface_name', 'interface_name')
@pass_state
def rmq_sub(state, interface_name):
    common_state_ops(state)
    rmq_transport_test.test_rmq_sub(state, interface_name=interface_name)


@click.group(name='mock1')
def mock1():
    pass


def hostname_option(f):
    return click.option('-h', '--hostname','hostname',
                        required=True,
                        expose_value=False,
                        callback=option_callback)(f)


def mock1_options(f):
    f = local_debug_option(f)
    f = external_debug_option(f)
    f = hostname_option(f)
    f = topo_file_option(f)
    f = log_debug(f)
    return f


@mock1.command(name='actor')
@mock1_options
@click.option('--timeout', 'timeout', default=60)
@pass_state
def mock1_actor(state, timeout):
    common_state_ops(state)
    mock_protocol_1.start_actor_v1(state, timeout)


@mock1.command(name='initiator')
@mock1_options
@click.option('--timeout', 'timeout', default=60)
@click.option('-m', '--message', 'msg', default='HELLO')
@click.option('-i', '--interface-name', 'interface_name', default=None)
@click.option('-d', '--dict-input', is_flag=True, default=False)
@pass_state
def mock1_initiator(state, msg, timeout, interface_name, dict_input):
    common_state_ops(state)
    if dict_input:
        msg = {
            'data': {
                'msg': msg
            }
        }
    mock_protocol_1.start_initiator(state, msg, timeout, interface_name)
