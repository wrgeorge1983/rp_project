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
        * specified interface
    * can share identity with one Actor without issue
* Actor
    * monitor and log all queues
    * discard messages received on an interface that were sent from that interface
* Message format:  
    msg:
        source_host: R1
        egress_interface: E2
        network_segment: BusA
        content: "foo"

## Milestone 2
* Actor
    * implement timer / flooding logic


## Milestone 3
* Rebase `rmq_transport` on async implementation of `TransportInstance`