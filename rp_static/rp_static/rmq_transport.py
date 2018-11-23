"""rmq_transport.py
define RabbitMQ based transport"""
import logging

import yaml
import pika


def get_logger():
    # sh = logging.StreamHandler()
    logger = logging.getLogger(__name__)
    # logger.addHandler(sh)
    # logger.setLevel(logging.INFO)
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
    log.info(f'Sent "{msg}" to queue "{queue}"')
    connection.close()


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
