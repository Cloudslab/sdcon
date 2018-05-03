#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys
import network_monitor_sflow
import topo_discovery, sdcon_config
from sdcon_config import SDCNodeIdType

from collections import defaultdict

SFLOW_FLOW_NORMAL = "ip_flows"
SFLOW_FLOW_TUNNEL = 'tunnel_flows'

## BW usage monitor functions...
def get_bw_usage_flow(src_ip, dst_ip, switch_dpid = "ALL"):
    # BW is a incoming bandwidth at the port (dataSource-2) of the switch.
    # Data: [{'key': '192.168.0.4,192.168.0.1','flowN': 3,'value': 2834,'agent': '192.168.99.100','dataSource': '6'}, ...]
    # BW usage of this flow, from 192.168.0.4 to 192.168.0.1, was 2834 Bytes/sec
    # at 49600000 switch, which comes at port 4 (6-4)
    
    # For debugging: SFLOW_COLLECTOR_URL/activeflows/192.168.99.120/ipflows/json?maxFlows=20&minValue=0&aggMode=max
    
    agent_ip = sdcon_config.switch_dpid_to_ip(switch_dpid)
    ip_key=src_ip+","+dst_ip
    json_object = network_monitor_sflow.get_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, SFLOW_FLOW_NORMAL, agent_ip)
    for js in json_object:
        if js['key'] == ip_key:
            return js['value']
    return None

def __parse_dump_topkeys_aggr_bw(js, exclude_key):
    bw = 0.0
    if 'topKeys' in js:
        for topkey in js['topKeys']:
            if exclude_key and topkey['key'] == exclude_key:
                continue
            bw += topkey['value']
    return bw

def __parse_dump_topkeys_keypair(js):
    flow_bw = []
    if 'topKeys' in js:
        for topkey in js['topKeys']:
            flow_bw.append( (topkey['key'], topkey['value']) )
    return flow_bw


def __parse_dump_get_bw_at_port(json_object, data_source, exclude_key=None):
    bw = 0.0
    for js in json_object:
        if int(js['dataSource']) == data_source:
            bw += __parse_dump_topkeys_aggr_bw(js, exclude_key)
    return bw

def __parse_dump_get_bw_all(json_object, exclude_key=None):
    switch_port_bw = defaultdict(list)
    for js in json_object:
        agent_ip = js['agent']
        switch_dpid = sdcon_config.switch_ip_to_dpid(agent_ip)
        data_source =  int(js['dataSource'])
        port = sdcon_config.data_source_to_port(switch_dpid, data_source)
        bw = __parse_dump_topkeys_aggr_bw(js, exclude_key)
        switch_port_bw[switch_dpid].append((port, bw))
    return switch_port_bw

def __parse_dump_get_bw_pair(json_object):
    switch_port_flow_bw = defaultdict(list)
    for js in json_object:
        # Get data and parse
        agent_ip = js['agent']
        switch_dpid = sdcon_config.switch_ip_to_dpid(agent_ip)
        data_source =  int(js['dataSource'])
        port = sdcon_config.data_source_to_port(switch_dpid, data_source)
        
        # Get src-dst pair to distinguish flow
        flow_bw_pairs = __parse_dump_topkeys_keypair(js)
        switch_port_flow_bw[switch_dpid].append((port, flow_bw_pairs))
    return switch_port_flow_bw

# This function returns a bandwidth usage at a single port at a switch 
def get_bw_usage_port_incoming(switch_dpid, switch_port, exclude_src_ip=None, exclude_dst_ip=None):
    # BW is a incoming bandwidth at the port (dataSource-2) of the switch.
    # Debug: SFLOW_COLLECTOR_URL/dump/192.168.99.100/ip_flows/json
    agent_ip = sdcon_config.switch_dpid_to_ip(switch_dpid)
    data_source = int(sdcon_config.port_to_data_source(switch_dpid, switch_port))
    exclude_key=None
    if exclude_src_ip and exclude_dst_ip:
        exclude_key = exclude_src_ip +","+ exclude_dst_ip
    
    json_object = network_monitor_sflow.get_sflow_dump(sdcon_config.SFLOW_COLLECTOR_URL, SFLOW_FLOW_NORMAL, agent_ip)
    bw = __parse_dump_get_bw_at_port(json_object, data_source, exclude_key)
    return bw

# This function returns a dict {switch1: [(port1, bw1), (port2, bw2), ...], } 
def get_bw_usage_all_incoming(exclude_src_ip=None, exclude_dst_ip=None, flow_name = SFLOW_FLOW_NORMAL):
    # Debug: SFLOW_COLLECTOR_URL/dump/ALL/ip_flows/json
    exclude_key=None
    if exclude_src_ip and exclude_dst_ip:
        exclude_key = exclude_src_ip +","+ exclude_dst_ip
    
    json_object = network_monitor_sflow.get_sflow_dump(sdcon_config.SFLOW_COLLECTOR_URL, flow_name, "ALL")
    switch_port_bw = __parse_dump_get_bw_all(json_object, exclude_key)
    return switch_port_bw

# This function returns a dict of {switch1: [(port1, [(flow11, bw11), (flow12,bw12), ...]), (port2, [(flow21,bw21,),...]), ...], switch2: ...} 
# For example, [ (40960020, 1, "192.168.0.1,192.168.0.9", 134), ...]
def get_bw_usage_all_link_flows(flow_name = SFLOW_FLOW_NORMAL):
    # Debug: SFLOW_COLLECTOR_URL/dump/ALL/ip_flows/json
    json_object = network_monitor_sflow.get_sflow_dump(sdcon_config.SFLOW_COLLECTOR_URL, flow_name, "ALL")
    switch_port_flow_bw = __parse_dump_get_bw_pair(json_object)
    return switch_port_flow_bw

# Get the total BW usage along the path.
def get_bw_usage_along_links(topo, path, exclude_src_ip=None, exclude_dst_ip=None):
    total_bw=0.0
    for (inport, this_node, outport) in topo.get_switch_port_map(path):
        total_bw += get_bw_usage_port_incoming(this_node, inport, exclude_src_ip, exclude_dst_ip)
    return total_bw

## Path monitoring using sFlow
def monitor_get_current_path_switches(src_ip, dst_ip):
    # For debugging: SFLOW_COLLECTOR_URL/flowlocations/ALL/ipflows/json?key=192.168.0.7,192.168.0.4
    json_object = network_monitor_sflow.get_sflow_flowlocations(sdcon_config.SFLOW_COLLECTOR_URL, SFLOW_FLOW_NORMAL, src_ip+","+dst_ip)
    switches = []
    ports = []
    for js in json_object:
        agent_ip = js['agent']
        switch_dpid = sdcon_config.switch_ip_to_dpid(agent_ip)
        data_source = js['dataSource']
        switches.append(switch_dpid)
        ports.append(sdcon_config.data_source_to_port(switch_dpid, data_source))
    return switches, ports

def monitor_get_current_path(topo, src_ip, dst_ip):
    current_switches, ports = monitor_get_current_path_switches(src_ip, dst_ip)
    all_paths = topo.find_all_path(src_ip, dst_ip)
    intersect_num=[]
    
    for path in all_paths:
        intersect_num.append( len(set(path) & set(current_switches)))
    
    cur_path_index = intersect_num.index(max(intersect_num))
    cur_path = all_paths[cur_path_index]
    
    # Verification
    if len(cur_path) > intersect_num[cur_path_index]+2: # 2 extra for host endpoint
        print "=========================="
        print "Error:monitor_get_current_path() cannot find a path!"
        print "All paths=",all_paths
        print "Swithces=",current_switches
        print "Returning the first path instead..."
        print "=========================="
    return cur_path

def monitor_get_current_path_port_map(topo, src_ip, dst_ip):
    path = monitor_get_current_path(topo, src_ip, dst_ip)
    return topo.get_switch_port_map(path)

def start_monitor():
    network_monitor_sflow.set_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, SFLOW_FLOW_NORMAL, ['ipsource','ipdestination'], 'bytes')
    network_monitor_sflow.set_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, SFLOW_FLOW_TUNNEL, ['ipsource.1','ipdestination.1'], 'bytes')

#####################################
## Test
#####################################

# Main
def _print_usage():
    print("Usage:\t python %s flow <src_IP> <dst_IP> \t - Get BW utilization from <src_IP> to <dst_IP>"%(sys.argv[0]))
    print("      \t python %s port <switch_DPID> <port> \t- Get incoming BW at <port> of <switch>"%(sys.argv[0]))

def print_ip(src_ip, dst_ip):
    print "BW usage %s -> %s = %s "%(src_ip, dst_ip, str(get_bw_usage_flow(src_ip, dst_ip)))

def print_switch(switch, port):
    print "Incoming BW at %s (Port %s)=%s"%(str(switch), str(port), str(get_bw_usage_port_incoming("4096000", "4")))

def test_monitor():
    print "\nTesting results..."
    print_ip("192.168.0.1", "192.168.0.2")
    print_ip("192.168.0.4", "192.168.0.7")
    
    print "192.168.0.[4,5,8,9] to 40960000:"
    print_switch("4096000", 4)
    print "192.168.0.[2,3,6,7] to 40960000:"
    print_switch("4096000", 2)
    print "192.168.0.1 -> 40960000:"
    print_switch("4096000", 1)

# Main
def main():
    start_monitor()
    
    if len(sys.argv) < 2:
        _print_usage()
        test_monitor()
        return
    
    if sys.argv[1] == "flow":
        print_ip(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "port":
        print_switch(sys.argv[2], sys.argv[3])
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()