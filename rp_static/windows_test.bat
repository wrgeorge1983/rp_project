set RP_TOPOLOGY_FILE=configs\topology-local.yml
set RP_CONFIG_FILE=configs\r1.config.yml

pipenv run rp_mock1 actor --log-debug --debug -h R1 --timeout 60
