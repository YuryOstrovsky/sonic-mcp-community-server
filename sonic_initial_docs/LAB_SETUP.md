# Lab Setup

## Management Network

Subnet: 10.46.11.0/24
Gateway: 10.46.11.1

| Device    | IP          |
| --------- | ----------- |
| Host      | 10.46.11.8  |
| SONiC VM1 | 10.46.11.50 |
| SONiC VM2 | 10.46.11.51 |

## Inter-switch Link

| Device | Interface | IP          |
| ------ | --------- | ----------- |
| VM1    | Ethernet0 | 192.168.1.1 |
| VM2    | Ethernet0 | 192.168.1.2 |

Connectivity between switches is verified via ping.

## Platform

* SONiC VS (KVM)
* Ubuntu 22.04 host
* libvirt/KVM virtualization

## Status

* SSH: working
* Ping: working
* Interfaces: up
