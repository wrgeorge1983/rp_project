import logging

import yaml
import click

def get_logger():
    sh = logging.StreamHandler()
    logger = logging.getLogger(__name__)
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)
    return logger

log = get_logger()


def get_configs(config_file, topology_file):
    log.info(f'Using config file: {config_file.name}')
    log.info(f'Using topology file: {topology_file.name}')
    config = yaml.load(config_file)
    topology = yaml.load(topology_file)
    log.debug(f'Got config: \n{yaml.dump(config)}')
    log.debug(f'Got topology: \n{yaml.dump(topology)}')
    return {
        'router_config': config,
        'topology': topology
    }


class State():
    def __init__(self):
        self.debug = False
        self.config_file = None
        self.topology_file = None


pass_state = click.make_pass_decorator(State, ensure=True)  # what does 'ensure' mean here?


def option_callback(ctx, param, value):
    state = ctx.ensure_object(State)
    log.info(f'callback got param: {param.name}')
    setattr(state, param.name, value)
    # state.topology_file = value
    return value


def debug_option(f):
    return click.option('--debug/--no-debug',
                        expose_value=False,
                        help='Enables or disables debug mode',
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
    f = debug_option(f)
    f = config_file_option(f)
    f = topo_file_option(f)
    return f


@click.command()
@common_options
@pass_state
def main(state):
    if state.debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(state.config_file, state.topology_file)


import pika


def get_mq_channel(config):
    mt_config = config['topology']['message_transport']
    if not mt_config['type'] == 'rabbitmq':
        raise ValueError('rmq pub/sub commands must be used with a message '
                         'transport type of "rabbitmq", not {mt_config["type"]}'                         )
    rmq_host = mt_config['hostname']
    log.info(f'Using {rmq_host} as rabbitMQ host')

    connection:pika.BlockingConnection = pika.BlockingConnection(pika.ConnectionParameters(rmq_host))
    channel = connection.channel()
    return channel, connection


@click.group(name='rmq')
def rmq():
    pass


@rmq.command(name='send')
@common_options
@click.option('-m', 'msg', default='Hello World!!!')
@click.option('-q', 'queue', default='hello')
@pass_state
def rmq_send(state, msg, queue):
    if state.debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(state.config_file, state.topology_file)

    channel, connection = get_mq_channel(config)
    channel.queue_declare(queue=queue)
    # msg = 'Hello World!!!'
    channel.basic_publish(exchange='',
                          routing_key=queue,
                          body=msg)
    log.info(f'Sent "{msg}" to queue "{queue}')
    connection.close()


@rmq.command(name='recv')
@common_options
@pass_state
def rmq_recv(state):
    if state.debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(state.config_file, state.topology_file)

    channel, _ = get_mq_channel(config)

    channel.queue_declare(queue='hello')
    def queue_callback(ch, method, properties, body):
        log.info(f'Received {body.decode()}')
    channel.basic_consume(queue_callback,
                          queue='hello',
                          no_ack=True)
    log.info('Waiting for messages forever.  To exit press CTRL-C')
    channel.start_consuming()


@rmq.command(name='pub')
@common_options
@click.option('-m', 'msg', default='Hello World!!!')
@pass_state
def rmq_pub(state, msg):
    if state.debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(state.config_file, state.topology_file)

    channel, connection = get_mq_channel(config)

    channel.exchange_declare(exchange='logs',
                             exchange_type='fanout')

    channel.basic_publish(exchange='logs',
                          routing_key='',
                          body=msg)

    log.info(f'Sent "{msg}"')
    connection.close()


@rmq.command(name='sub')
@common_options
@pass_state
def rmq_sub(state):
    if state.debug:
        log.setLevel(logging.DEBUG)

    config = get_configs(state.config_file, state.topology_file)

    channel, _ = get_mq_channel(config)

    queue = channel.queue_declare(exclusive=True)
    queue_name = queue.method.queue

    log.debug(f'binding queue: {queue_name}')

    channel.queue_bind(exchange='logs',
                       queue=queue_name)

    def queue_callback(ch, method, properties, body):
        log.info(f'Received {body.decode()}')

    channel.basic_consume(queue_callback,
                          queue=queue_name,
                          no_ack=True)

    log.info('Waiting for messages forever.  To exit press CTRL-C')
    channel.start_consuming()



