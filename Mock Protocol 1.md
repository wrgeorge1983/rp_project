# Mock Protocol 1.0 Specification

## Overview
* Two roles:
    * Initiator
        * one-off pub messages to specified networks, then exit
    * Actor
        * monitor *all* queues for messages
            * Discard any messages sent by self *from this interface*
        * log *all* messages IAW logging configuration
        * If timer is already running, then continue
        * If timer is not already running, then start it, then continue
        * On timer expiration flood message to all peers on all connected networks
            * timer expiration 5 seconds?


## Milestone 1  
* Initiator
    * given hostname and topology file
        * attach to appropriate RMQ exchanges
    * can pub messages to:
        * all interfaces
        * specified interface
    * can share identity with one Actor without issue
* Actor
    * monitor and log all queues associated with this router identity
    * discard messages received on an interface that were sent from that interface
* Message format:  
```yaml
    msg:
        source_host: R1
        egress_interface: E2
        network_segment: BusA
        content: "foo"
```
---
```json
{
  "type": "routing_update",
  "data": {
    "1.1.1.0/30": 2
  }
}
``` 
becomes
```json
{
  "source_host": "R1",
  "egress_interface": "E2",
  "netowrk_segment": "BusA",
  "content": {
    "type": "routing_update",
    "data": {
      "1.1.1.1/30": 2
    }
  }
}
```
---
```json
"reboot now"
```
becomes
```json
{
  "source_host": "R1",
  "egress_interface": "E2",
  "network_segment": "BusA",
  "content": "reboot now"
} 
```
---
```python
TransportMessage(content='foo', egress_interface='E1')
```
becomes
```json
{
  "source_host": "R1",
  "egress_interface": "E1",
  "network_segment": "NetA",
  "content": "foo"
}
```
---


## Milestone 2
* Actor
    * implement timer / flooding logic


## Milestone 3
    * Implement Actor as Class, not functions sharing global state