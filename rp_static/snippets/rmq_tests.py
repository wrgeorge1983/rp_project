import pika

def get_configs(config_file, topo_file):
    return {}


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
    config = get_configs(state.config_file, state.topology_file)

    channel, connection = get_mq_channel(config)

    channel.exchange_declare(exchange='logs',
                             exchange_type='fanout')

    channel.basic_publish(exchange='logs',
                          routing_key='',
                          body=msg)

    log.info(f'Sent "{msg}"')
    connection.close()


def rmq_sub(state):
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
