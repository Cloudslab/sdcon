# SDCon: SDC Controller software
This program is to manage SDC (Software-Defined Clouds) in autonomic mechanism.

## Pre-requisite sysem configuration
This program is built on top of several assumptions and thus these need to be set up before usage.

### Basic infrastructure
OpenStack: admission control, VM allocation, tenant authentication, and other cloud management functionalities.

1. OpenStack Neutron: manages VM networks. Neutron is used to create/manage virtual networks on tenants side. 

2. OpenDayLight: SDN controller. Basically all switches are connected to ODL, while networks on hosts and VMs are managed by OS Neutron.

3. OpenVSwitch: software-based switch. All switches composing our topology are OVS, which can be easily managed from ODL.


### Network topology
Base network topology is 3-tier fat-tree multi-path topology. There are Core, Aggregate, and Edge switches, where Edge switches are connected to hosts.

### Network addresses
* ``192.168.0.X`` : For a tenant network. All hosts have this IP range.

* ``192.168.99.X`` : For a management network. Switches can be accessed through this IP range.

* IP range of hosts: ``192.168.99.1`` - ``192.168.99.99`` / ``192.168.99.130`` - ``192.168.99.254``

* IP range of switches: ``192.168.99.100`` - ``192.168.99.129``

* OS and ODL Controller: ``192.168.99.1``

## Switch Setup

### OVS bridge in a switch
In each switch, an OVS bridge is created to forward packets between ports using this command:
```
sudo ovs-vsctl add-br ovsbr0
```

All ports are added to the bridge.
```
sudo ovs-vsctl add-port ovsbr0 eth1
sudo ovs-vsctl add-port ovsbr0 eth2
sudo ovs-vsctl add-port ovsbr0 eth3
sudo ovs-vsctl add-port ovsbr0 eth4
```

Set SDN controller for the ovsbr0 bridge.
```
sudo ovs-vsctl set-controller ovsbr0 tcp:192.168.99.1:6633
```
Note that TCP port 6633 is for ODL OpenFlow. Another port is used for OS Neutron to manage the hosts OpenFlow network.

### Setup DPID
In addition to the differentiated IP addresses, switches are set up with a specific DPID (mac address) in order to identify their tiers easily.

* Core switches: ``40960000`` - ``40960009`` = (0x2710000 - 0x2710009)

* Aggr switches: ``40960010`` - ``40960019`` = (0x271000A - 0x2710013)

* Edge switches: ``40960020`` - ``40960029`` = (0x2710014 - 0x271001D)


DPID can be set up using OVS management command:
 ```
 sudo ovs-vsctl set bridge ovsbr0 other-config:hwaddr=00:00:02:71:00:00
 ```

Note that the last two digits in DPID is same as the last two digits in IP address of the switch. For example, 409600**27** switch will have an IP address 192.168.99.1**27**.

This is important to identify a switch using both IP address and DPID, because ODL uses both identifier on different purpose.

### Switch ports (interface names)
Port number in OVS bridge at each switch is matching to the name of interface. For example, the port number of an interface `eth2` is set to `2` in `ovsbr0`.

Port number to interface name mapping can be checked:
  ```
  sudo ovs-ofctl show ovsbr0
  ```

### OVS setting for ODL OVSDB plugin.
We used OVSDB plugin in order to manage QoS queues in OVS switches. OVSDB requires to set an external ID to identify different OVS switches. This command sets an external ID ('ovsdb:40960000') for OpenDayLight OVSDB plugin.
  ```
  sudo ovs-vsctl set open_vswitch . external-ids:opendaylight-iid=/network-topology:network-topology/network-topology:topology[network-topology:topology-id=\'ovsdb:1\']/network-topology:node[network-topology:node-id=\'ovsdb:40960000\']
  ```

Also, OVS manager should be set in order to control the OVSDB by the controller.

  ```
  sudo ovs-vsctl set-manager tcp:192.168.99.1:6641
  ```

Note that port 6641 is for ODL OVSDB plugin. Port 6640 was used by OS Neutron to manage OVSDB.

## ``network_defpath.py``: set default path in multi-path Fat-Tree topology using source-address ECMP

Default path for Fat-Tree can be set up using ``network_defpath.py`` program. It uses source-address packet distribution among multiple paths.
To initiate default paths:

```
python network_defpath.py set
```

To delete the default paths initiated with this program, use:

```
python network_defpath.py del
```

## ``network_monitor``: monitoring network using sFlow

This is a python module to get the monitored mesurements of the network using sFlow.
Make sure that sFlow is properly set up and running on the controller.

### sFlow setup

 1. Set up sFlow - switches

   For each OVS node, use the following command to add sFlow agent that sends the monitored statististics to the sFlow controller.

   ```
   sudo ovs-vsctl -- \
     --id=@sflow create sflow agent=eth0 target="192.168.99.1\:6343" header=128 sampling=64 polling=10 -- \
     set bridge ovsbr0 sflow=@sflow
   ```
   * agent=eth0
     eth0 is the network interface that connects to the sFlow collector (192.168.99.1)
   * target="192.168.99.1\:6343
     IP and port of the sFlow collector
   * bridge ovsbr0
     a bridge to monitor the network packets.
     Note that sFlow reports **incoming** traffic of each port in the specified OVS bridge.
     If you want to monitor multiple bridges, set **sflow** for every bridge.

 2. Set up sFlow - collector

   An sFlow collector is in charge of gathering monitored data from each agent and providing the aggregated measurements to the user.
   We use (sFlow-rt)[http://www.sflow-rt.com/download.php], which is simple to install and easy to use. It also provides a basic web UI with several applications optionally downloadable from their website.

   sFlow-rt has two port numbers. ``sflow.port`` is for collecting data from switches, and ``http.port`` is to provide REST API to the users. These settings can be found in ``start.sh`` script.

   ``network_monitor`` module uses REST API of ``sFlow-rt`` program.

### Usage
Once sFlow is configured at every switch, as well as installing sFlow-rt, ``network_monitor`` can be used to get the network monitored data.

 * ``python network_monitor.py flow <src> <dst>`` shows a BW usage from src to dst host.

 * ``python network_monitor.py <switch_id> <port>`` shows an incoming BW usage at port of the switch.

It also includes many APIs which can be used to get monitored data. Note that all the information from this module is a real time. For example, the current path returned from ``monitor_get_current_path(topo, src, dst)`` function is a path that is used at the moment. If there is no packet using the network from src and dst, it will return None, which does not mean that there is no path. Instead, it intends there is no packet from src to dst currently seen in the network.

## ``sdc_viz.py``: visualization module for monitor.

This is a web based networking monitoring UI, that shows the real-time network usage. It uses ``topo_discovery`` to get the network topology and ``sdc_odl_monitor`` to get the real-time bandwidth usage.

```
python sdc_viz.py
```

Once the module is running up, it creates a HTTP server that can be retrieved from any web browser. The monitoring data is updated every second.

For web rendering, we use (D3 Javascript library)[https://d3js.org/].

## ``network_manager_qos``: manages queues in switches for QoS (bandwidth guarantee) through OVS

This program is to manage QoS of the network. It manages QoS and Queue entries in OVS, and sets a specific flow to use the established QoS and Queues to provide end-to-end minimum BW guarantees.

This module uses OVSDB plugin in ODL in order to create and delete QoS and Queue entries. After that, the flow rules are pushed through the normal OF for a specific source and destination pair.

**CAUTION**

Be careful to use this module. It can make a critical effect to the network configuration because it directly manages OVSDB of all switches. If something happens in this module, it can mess up the entrie network.

### Set OVSDB plugin at ODL and switches
At ODL, simply install (OVSDB plugin)[http://docs.opendaylight.org/en/stable-carbon/developer-guide/ovsdb-developer-guide.html#] feature and change the port number of OVSDB plugin to avoid any conflict.
**Before** installing the feature, the default port (6640) for the OVSDB manager can be changed in the config file:
  in ``etc/custom.properties``:

    ```
    ovsdb.listenPort=6640
    ```

After change the port, the plugin can be installed in ODL karaf console:
    ```
    karaf> feature:install odl-ovsdb-southbound-impl
    ```
For each switch, use the following command to set up the OVS to connect OVSDB plugin in ODL.
    ```
    sudo ovs-vsctl set-manager tcp:192.168.99.1:6641
    ```

### Testing this module

Currently it provides only testing command.

* ``python network_manager_qos.py test-set`` : create several test queues between two hosts.
* ``python network_manager_qos.py test-del`` : delete the test queues created from ``test-set``.

Please refer to the source code for more details.

## ``topo_discovery.py``: retrieves network topology.

This is a fundamental library used for all modules. It retrieves the network topology information using ODL's REST API, and provides the relavant information to each module.

Simply run the python using ``python topo_discovery.py`` to get the network topology.

Use the relavant APIs in this module to get any information about the network.
