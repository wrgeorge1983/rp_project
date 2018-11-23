
# NEXT TO IMPLEMENT IS 
* Topology_config parser as shown in [architecture 2 diagram](https://www.lucidchart.com/invitations/accept/37285e1d-19e9-4124-bea7-70b43f01e268)


# architecture
### what are we building?  What are we building it with?
* RIPv2 in the abstract
    * in a way that could, plausibly, be make concrete in the future
    * generic virtual router that has tables (RIB, FIB, etc) but doesn't, necessarily, actually forward any packets
        * if we can't forward real packets, then we need a way to simulate them to determine forwarding behavior
        * so really we first need to implement static routing
* ran in containers so that we can spin up lots of these to talk to eachother, build arbitrary topologies, etc.
### goals? milestones? etc?
* adjacent control planes

### scope?  list of features, by priority
* Provision routers in arbitrary topology, with a controlled and consistent configuration (i.e. R1e0 connects to R2e0 *every* time you spin it up, etc) 
    * we don't actually *have* to use the "real" interfaces of the containers





### how do they talk to eachother?  

RabbitMQ Pub/Sub for now, need to make sure we leave it open for changing our minds later.
### how are they configured.
  
Docker topology is dead simple, all containers in the same network
Detailed topology is handled in-application in a configuration file for that purpose
Each router configuration is handled in its own config
  
  
  
any new network name gets its own RMQ exchange/queues
routers that have interfaces on a given network pub/sub to the appropriate exchanges/queues
routers determine which networks their interfaces are attached to via topology config



    rmq exhanges:  
        - netA  
            msg:  
                network_name: netA  
                src: 1.1.1.1
                dest: 1.1.1.2
                protocol: tcp
                src_port: 80
                dest_port: 5866
        - netB
        - netC





