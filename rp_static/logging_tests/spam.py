# myapp.py
import logging
import auxiliary_module
import yaml
import logging_tree

import logging.config

with open('loggingconf.yml') as infil:
    log_config = yaml.load(infil)

logging.config.dictConfig(log_config)

# logging.config.fileConfig('logging.conf')

# create logger
logger = logging.getLogger(__name__)



def main():
    # logging.basicConfig(level=logging.DEBUG)
    logger.info('Started')
    auxiliary_module.do_something()
    logger.info('Finished')
    logging_tree.printout()


if __name__ == '__main__':
    main()
