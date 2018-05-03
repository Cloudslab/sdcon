#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys
import json, enum
from collections import defaultdict
import copy, time

import cloud_manager, topo_discovery, network_manager, network_defpath, network_manager_qos

#TEST_IMAGE_NAME = "jay-pisdc-experiment"
#TEST_NETWORK_NAME = "jay-flat"
    
class VmSpec:
    def __init__(self, vm_name):
        self.name = vm_name
        self.mips = 0
        self.cores = 0
        self.memory = 0
        self.bandwidth = 0
        self.storage_size = 0
        self.flavor_name = ""
        self.image_name=""
        self.network_name=""
    
    def set_flavor(self, flavor_name):
        self.flavor_name = flavor_name
    
    def set_property(self, storage_size=None, bw=None, mips=None, cores=None, memory=None,
        image_name=None, network_name=None):
        if storage_size:
            self.storage_size = storage_size
        if bw:
            self.bandwidth = bw
        if mips:
            self.mips = mips
        if cores:
            self.cores = cores
        if memory:
            self.memory = memory
        if image_name:
            self.image_name=image_name
        if network_name:
            self.network_name=network_name
    
    def set_bandwidth(self, bandwidth):
        self.bandwidth = bandwidth
    
    def sync_flavor(self, conn_os):
        if self.flavor_name == "":
            flv = cloud_manager.get_flavor(conn_os, self.cores, self.memory)
            self.flavor_name = flv.name
        self.cores, self.memory = cloud_manager.get_flavor_cpu_memory(conn_os, self.flavor_name)
    
    def __str__(self):
        return "VmSpec: name=%s, flavor=%s, cpu=%s, memory=%s"%(str(self.name), str(self.flavor_name), str(self.cores), str(self.memory))
    def __repr__(self):
        return "VmSpec: name=%s, flavor=%s, cpu=%s, memory=%s, bw=%s"%(str(self.name), str(self.flavor_name), str(self.cores), str(self.memory), str(self.bandwidth))

class VirtualTopology:
    def __init__(self, json_file, conn_os):
        self.vms = {}
        self.links = [] # ("from", "to", bandwidth)
        self.json_file = json_file
        self.conn_os = conn_os
        self.parse_json()
    
    def parse_json(self):
        data = json.load(open(self.json_file))
        for node in data["nodes"]:
            self.__parse_json_node(node)
        
        for link in data["links"]:
            self.__parse_json_link(link)
    
    def __parse_json_node(self, node):
        vm = VmSpec(node["name"])
        if "flavor" in node:
            vm.set_flavor(node["flavor"])
            vm.set_property(image_name=node["image"], network_name=node["network"])
        else:
            vm.set_property(storage_size = node["size"],
                bw = node["bw"],
                mips = node["mips"],
                cores = node["pes"],
                memory = node["ram"],
                image_name=node["image"],
                network_name=node["network"])
        
        vm.sync_flavor(self.conn_os)
        self.vms[vm.name] = vm    
    
    def __parse_json_link(self, link):
        bandwidth = 0
        if "bandwidth" in link:
            bandwidth = int(link["bandwidth"])
        if bandwidth > 0:
            vm_name_src = link["source"]
            vm_name_dst = link["destination"]
            self.links.append( (vm_name_src, vm_name_dst, bandwidth) )
            if vm_name_src in self.vms:
                self.vms[vm_name_src].set_bandwidth(bandwidth)
    
    def get_vms(self):
        return self.vms.values()
    
    def get_links(self):
        return list(self.links)
    
    def get_vm_spec(self, vm_name):
        return self.vms[vm_name]


class TopologyInfoNode:
    class Type(enum.Enum):
        Root = 0
        Pod = 1
        Edge = 2
        Host = 3
    
    def __init__(self, type, parent):
        self.name=""
        self.type=type
        self.vcpus=0
        self.vcpus_used=0
        self.memory_size=0
        self.memory_free=0
        self.memory_used=0
        self.running_vms=0
        self.parent = parent
        self.subtree= []
    
    def assign_vm(self, vm_spec):
        self.vcpus_used += vm_spec.cores
        self.memory_used += vm_spec.memory
        self.memory_free -= vm_spec.memory
        self.running_vms += 1
        if self.parent:
            self.parent.assign_vm(vm_spec)
    
    def aggregate(self):
        if len(self.subtree) > 0:
            for sub in self.subtree:
                sub.aggregate()
                self.vcpus += sub.vcpus
                self.vcpus_used += sub.vcpus_used
                self.memory_size += sub.memory_size
                self.memory_used += sub.memory_used
                self.memory_free += sub.memory_free
                self.running_vms += sub.running_vms
    
    def get_sub_hosts(self):
        if self.type== TopologyInfoNode.Type.Host:
            return [self]
        sub_hosts = []
        for sub in self.subtree:
            sub_hosts += sub.get_sub_hosts()
        return sub_hosts
    
    def __repr__(self):
        subtree_str = str(self.subtree)
        
        return "%stype=%s, %s, vcpus_free:'%s/%s', memory_free:'%s/%s'\n%s" % (
            "\t"*TopologyInfoNode.Type(self.type).value,
            str(TopologyInfoNode.Type(self.type).name), 
            str(self.name),
            str(self.vcpus-self.vcpus_used), str(self.vcpus), 
            str(self.memory_size-self.memory_used), str(self.memory_size), 
            str(subtree_str))

class TopologyInfo:
    def __init__(self, conn_os):
        self.conn_os = conn_os
        self.all_hosts = {}
        self.__build_hosts()
        self.topology = self.get_topology()
    
    def __build_hosts(self):
        hosts = cloud_manager.get_all_hosts(self.conn_os)
        for host in hosts:
            self.all_hosts[host.name] = host
    
    def __get_host(self, host_name):
        return self.all_hosts[host_name]
    
    def get_topology(self):
        topo_info = topo_discovery.get_topology_info()
        
        topo_node = TopologyInfoNode(TopologyInfoNode.Type.Root, None)
        for pod in topo_info:
            pod_node = TopologyInfoNode(TopologyInfoNode.Type.Pod, topo_node)
            for edge_hosts in pod:
                edge_node = TopologyInfoNode(TopologyInfoNode.Type.Edge, pod_node)
                for host_ip in edge_hosts:
                    host_name = sdcon_config.ip_to_hostname(host_ip)
                    host = self.__get_host(host_name)
                    
                    host_node = TopologyInfoNode(TopologyInfoNode.Type.Host, edge_node)
                    host_node.name  = host.name
                    host_node.vcpus = host.vcpus
                    host_node.vcpus_used  = host.vcpus_used
                    host_node.memory_size = host.memory_size
                    host_node.memory_used = host.memory_used
                    host_node.memory_free = host.memory_free
                    host_node.running_vms = host.running_vms
                    edge_node.subtree.append(host_node)
                pod_node.subtree.append(edge_node)
            topo_node.subtree.append(pod_node)
        topo_node.aggregate()
        return topo_node
    
    def get_pods(self):
        return list(self.topology.subtree)
    
    def get_all_edges(self):
        edges = []
        for pod in self.topology.subtree:
            for edge in pod.subtree:
                edges.append(edge)
        return edges
    
    def find_hostnode(self, host_name):
        topo_node = self.topology
        for pod_node in topo_node.subtree:
            for edge_node in pod_node.subtree:
                for host_node in edge_node.subtree:
                    if host_node.name == host_name:
                        return host_node
        return None
    
    def get_all_hosts(self):
        return self.topology.get_sub_hosts()
    
    def get_nearby_hosts(self, host_to_find, is_search_pod=False):
        # Find the edge where host is connected and return the edge info.
        for pod in self.topology.subtree:
            for edge in pod.subtree:
                for host in edge.subtree:
                    if host.name == host_to_find:
                        if is_search_pod:
                            return pod
                        else:
                            return edge
    
    def __repr__(self):
        return str(self.topology)

__saved_topo_info = None
def _get_topo_info(conn_os):
    global __saved_topo_info
    if __saved_topo_info == None:
        __saved_topo_info = TopologyInfo(conn_os)
    return __saved_topo_info

def aggregate_vms(vms):
    aggregated= VmSpec("__aggr")
    for vm in vms:
        aggregated.cores += vm.cores
        aggregated.memory += vm.memory
        aggregated.bandwidth += vm.bandwidth
    return aggregated

def get_free_bw(host):
    TOTAL_BW = 100000000 # 100 Mbits/s
    BW_OVERSUBSCRIPTION = 4 # 
    each_bw = TOTAL_BW * BW_OVERSUBSCRIPTION // (host.running_vms+1)  # Assumming all VMs share at same time.
    
    #return max(TOTAL_BW, each_bw)
    return 10000000000

def is_host_available(vm_spec, host_inst):
    free_cpu = host_inst.vcpus - host_inst.vcpus_used
    free_memory = host_inst.memory_free 
    free_bw = get_free_bw(host_inst)  #### ToDo. How to make sure free BW?
    
    if free_cpu >= vm_spec.cores and free_memory >= vm_spec.memory and free_bw >= vm_spec.bandwidth:
        return True
    return False

def get_available_host(vm_spec, host_candidate):
    # Get the list of hosts with enough resources for the requirement.
    available_hosts=[]
    for host in host_candidate:
        if is_host_available(vm_spec, host):
            available_hosts.append( host )
    
    return available_hosts

def get_host_most_full(vm_spec, host_candidate):
    # return the most full host (calculate cpu core usage)
    hosts = get_available_host(vm_spec, host_candidate)
    
    if len(hosts) > 0:
        # sort available host in increasing order of available CPU
        hosts.sort(key=lambda x: (x.vcpus - x.vcpus_used) + int((x.vcpus - x.vcpus_used)/x.vcpus)*100, reverse=False)
        print "Debug: selected host = "+cloud_manager.host_to_str(hosts[0])
        return hosts[0]
    
    print "Debug: get_host_most_full - not available host"
    return None

def get_hostmap_most_full(conn_os, vms, **kwargs):
    map_vm_host={}
    
    topo_info = _get_topo_info(conn_os)
    all_hosts = topo_info.get_all_hosts()
    for vm in vms:
        host = get_host_most_full(vm, all_hosts)
        if host:
            map_vm_host[vm.name] = host.name
            host.assign_vm(vm)
    return map_vm_host

def get_host_name_list_of_vms(conn_os, vms):
    host_names = set()
    for vm in vms:
        host_name = cloud_manager.get_vm_hostname(conn_os, vm.name)
        host_names.add(host_name)
    return list(host_names)

def find_bandwidth_aware_topo_for_vms(topo_info, vms):
    topo_list = []
    aggr_vm = aggregate_vms(vms)
    
    # 1. can one compute node host all vms?
    all_hosts = topo_info.get_all_hosts()
    hosts = get_available_host(aggr_vm, all_hosts)
    if len(hosts) > 0:
        # sort available host in decreasing order of available bandwidth
        hosts.sort(key=lambda x: x.running_vms, reverse=False)
        for host in hosts:
            topo_list.append(host)
    
    # 2. can compute nodes in one edge switch host the vms?
    all_edges = topo_info.get_all_edges()
    edges = get_available_host(aggr_vm, all_edges)
    if len(edges) > 0:
        # sort available  in decreasing order of available bandwidth
        edges.sort(key=lambda x: x.running_vms, reverse=False)
        for edge in edges:
            topo_list.append(edge)
    
    all_pods = topo_info.get_pods()
    pods = get_available_host(aggr_vm, all_pods)
    if len(pods) > 0:
        # sort available  in decreasing order of available bandwidth
        pods.sort(key=lambda x: x.running_vms, reverse=False)
        for pod in pods:
            topo_list.append(pod)
    return topo_list

def get_hostmap_bandwidth_aware(topo_info, vms):
    # Returns a dict {vm: host} for topology-aware vm-host map.
    map_vm_host={}
    
    topo_candidate = find_bandwidth_aware_topo_for_vms(topo_info, vms)
    
    placed_all = True
    
    for topo_org in topo_candidate:
        topo = copy.deepcopy(topo_org)
        placed_all = True
        map_vm_host={}
        
        for vm in vms:
            hosts = topo.get_sub_hosts()
            host = get_host_most_full(vm, hosts)
            if host:
                map_vm_host[vm.name] = host.name
                host.assign_vm(vm)
            else:
                placed_all = False
                break
        
        if placed_all:
            break
    
    if not placed_all:
        map_vm_host={}
    
    return map_vm_host

def get_hostmap_topo_aware(conn_os, vms, **kwargs):
    placed_vms = None
    if "placed_vms" in kwargs:
        placed_vms = kwargs["placed_vms"]
    
    # Returns a dict {vm: host} for topology-aware vm-host map.
    topo_info = _get_topo_info(conn_os)
    map_vm_host={}
    vms_to_be_placed = list(vms)
    
    if placed_vms and len(placed_vms) > 0:
        # Find a host nearest to the placed VMs.
        pl_host_names = get_host_name_list_of_vms(conn_os, placed_vms)
        
        for vm in vms:
            # First, try the same host.
            hosts = []
            for host_name in pl_host_names:
                hosts.append(topo_info.find_hostnode(host_name))
            host = get_host_most_full(vm, hosts)
            if host:
                map_vm_host[vm.name] = host.name
                vms_to_be_placed.remove(vm)
                host.assign_vm(vm)
                continue
            
            # Second, try the host under same edge.
            host_group = []
            for host_name in pl_host_names:
                host_group.append(topo_info.get_nearby_hosts(host_name))
            host_group = list(set(host_group)) # remove duplicate
            
            hosts = []
            for hg in host_group:
                hosts += hg.get_sub_hosts()
            host = get_host_most_full(vm, hosts)
            if host:
                map_vm_host[vm.name] = host.name
                vms_to_be_placed.remove(vm)
                host.assign_vm(vm)
                continue
            
            # Last, try the host unde same pod
            host_group = []
            for host_name in pl_host_names:
                host_group.append(topo_info.get_nearby_hosts(host_name, True))
            host_group = list(set(host_group)) # remove duplicate
            
            hosts = []
            for hg in host_group:
                hosts += hg.get_sub_hosts()
            host = get_host_most_full(vm, hosts)
            if host:
                map_vm_host[vm.name] = host.name
                vms_to_be_placed.remove(vm)
                host.assign_vm(vm)
                continue
            
            all_hosts = topo_info.get_all_hosts()
            host = get_host_most_full(vm, all_hosts)
            if host:
                map_vm_host[vm.name] = host.name
                vms_to_be_placed.remove(vm)
                host.assign_vm(vm)
                continue
    else:
        map_vm_host = get_hostmap_bandwidth_aware(topo_info, vms)
        for vm_name in map_vm_host:
            vm = (item for item in vms_to_be_placed if item.name == vm_name).next()
            vms_to_be_placed.remove(vm)
    
    if len(vms_to_be_placed) > 0:
        print "More VMs...", vms_to_be_placed
        # Find a new place to place this VM.
        pods = topo_info.get_pods()
        pods.sort(key=lambda x: x.vcpus - x.vcpus_used, reverse=True) # Least full pod
        for pod in pods:
            edges = list(pod.subtree)
            edges.sort(key=lambda x: x.vcpus - x.vcpus_used, reverse=True)
            for edge in edges:
                hosts = list(edge.subtree)
                hosts.sort(key=lambda x: x.vcpus - x.vcpus_used, reverse=True)
                for host in hosts:
                    vms_to_be_placed2 = list(vms_to_be_placed)
                    for vm in vms_to_be_placed2:
                        if is_host_available(vm, host):
                            map_vm_host[vm.name] = host.name
                            vms_to_be_placed.remove(vm)
                            host.assign_vm(vm)
    
    if len(vms_to_be_placed) > 0:
        print "Cannot find a suitable host for: ", vms_to_be_placed
        print topo_info
    return map_vm_host

def set_dynamic_flow_vm(src_vm_ip, dst_vm_ip, src_compute, dst_compute):
    if src_compute == dst_compute:
        print "Debug: same source and destination. No dynamic flow: %s (host=%s) -> %s (host=%s)"%(
        str(src_vm_ip), str(src_compute), str(dst_vm_ip), str(dst_compute) )
        return
    # Set a dynamic path from src to dst vm.
    print "Debug: setting dynamic flow from %s (host=%s) -> %s (host=%s)"%(
        str(src_vm_ip), str(src_compute), str(dst_vm_ip), str(dst_compute) )
    network_manager.create_special_path(src_compute, dst_compute, src_vm_ip, dst_vm_ip)

DYNAMIC_FLOW_INTERVAL = 60

def set_dynamic_flows(conn_os, links, **kwargs):
    src_dst_pairs = []
    for link in links:
        (src_vm_name, dst_vm_name, bw) = link
        print "Debug: getting link from %s to %s (%s)"%(src_vm_name, dst_vm_name, str(bw))
        src_vm_ip = cloud_manager.get_vm_ip(conn_os, src_vm_name)
        dst_vm_ip = cloud_manager.get_vm_ip(conn_os, dst_vm_name)
        src_compute = cloud_manager.get_host_ip_of_vm_ip(conn_os, src_vm_ip)
        dst_compute = cloud_manager.get_host_ip_of_vm_ip(conn_os, dst_vm_ip)
        
        src_dst_pairs.append((src_vm_ip, dst_vm_ip, src_compute, dst_compute))
        
    interval = DYNAMIC_FLOW_INTERVAL / len(links)
    
    while True:
        for src_vm_ip, dst_vm_ip, src_compute, dst_compute in src_dst_pairs:
            set_dynamic_flow_vm(src_vm_ip, dst_vm_ip, src_compute, dst_compute)
            time.sleep(interval)

def set_bandwidth_flows(conn_os, links, **kwargs):
    for link in links:
        (src_vm_name, dst_vm_name, bw) = link
        print "Debug: setting bandwidth from %s to %s (%s)"%(src_vm_name, dst_vm_name, str(bw))
        src_vm_ip = cloud_manager.get_vm_ip(conn_os, src_vm_name)
        dst_vm_ip = cloud_manager.get_vm_ip(conn_os, dst_vm_name)        
        src_compute = cloud_manager.get_host_ip_of_vm_ip(conn_os, src_vm_ip)
        dst_compute = cloud_manager.get_host_ip_of_vm_ip(conn_os, dst_vm_ip)
        
        if src_compute == dst_compute:
            print "Debug: same source and destination. No bandwidth alloc: %s (host=%s) -> %s (host=%s)"%(
            str(src_vm_ip), str(src_compute), str(dst_vm_ip), str(dst_compute) )
            continue
        network_manager_qos.add_entry(src_vm_ip, dst_vm_ip, bw)
    
    network_manager_qos.apply_qos()

def get_vms_placed(conn_os, vms):
    placed_vms = []
    new_vms = []
    # This function returns a list of VMs already placed in the cloud.
    for vm in vms:
        vm_ins = cloud_manager.get_vm(conn_os, vm.name)
        if vm_ins != None:
            placed_vms.append(vm)
        else:
            new_vms.append(vm)
    return placed_vms, new_vms

def place_vm(conn_os, vms, vm_host_map):
    for vm in vms:
        if vm.name in vm_host_map:
            host = vm_host_map[vm.name]
            create_vm(conn_os, vm, host)

def create_vm(conn_os, vm, hostname):
    print "Debug: Creating... VM=%s in hostname=%s"%(str(vm), str(hostname))
    #cloud_manager.create_vm(conn_os, "jay2-wikibench-db", "wikibench-database.xlarge", "m1.xlarge", "jay-flat", "compute6")
    cloud_manager.create_vm(conn_os, vm.name, vm.image_name, vm.flavor_name, vm.network_name, hostname)
    print "Debug: Created.... VM=%s in hostname=%s"%(str(vm), str(hostname))

def virtual_deploy_vm(conn_os, virt_files, vm_alg, simulate = False):
    print "Starting VM deployment..."
    print "========== Physical topo before deployement... =========="
    print str(_get_topo_info(conn_os))
    print "..."
    for virt_file in virt_files:
        vtopo = VirtualTopology(virt_file, conn_os)
        vms = vtopo.get_vms()
        placed_vms, new_vms = get_vms_placed(conn_os, vms)
        
        new_vms.sort(key=lambda x: x.cores, reverse=True)
        
        fun_get_hostmap = VM_PLACEMENT_ALGORITHMS[vm_alg]
        vm_host_map = fun_get_hostmap(conn_os, new_vms, placed_vms = placed_vms)
        
        print "=============== VM placement map... ==============="
        for vm in new_vms:
            print "VM: %s ====> %s !!! (VM spec: %s)"%(str(vm.name), vm_host_map[vm.name], str(vm))
        print "==================================================="
    
        if not simulate:
            place_vm(conn_os, new_vms, vm_host_map)
            
            last_vm = new_vms[-1]
            last_vm_ip = cloud_manager.get_vm_ip(conn_os, last_vm.name)
            network_defpath.set_default_paths()
    
    print "========== Physical topo after deployement... =========="
    print str(_get_topo_info(conn_os))
    print "========================================================="


def virtual_deploy(virt_files, vm_alg, net_arg, net_only = False, simulate = False):
    conn_os = cloud_manager.connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    if not net_only:
        virtual_deploy_vm(conn_os, virt_files, vm_alg, simulate)
    virtual_deploy_network(conn_os, virt_files, net_arg)

def virtual_deploy_network(conn_os, virt_files, net_arg):
    if net_arg == None or net_arg not in NETWORK_MANAGEMENT_ALGORITHMS:
        print "Error! cannot find net_arg=",net_arg
        return False
    
    links = []
    for virt_file in virt_files:
        vtopo = VirtualTopology(virt_file, conn_os)
        links += vtopo.get_links()
        
    print "Net-policy= %s, links= %s"%(str(net_arg), str(links))
    
    #"df" : set_dynamic_flows
    #"bw" : set_bandwidth_flows
    fun_net = NETWORK_MANAGEMENT_ALGORITHMS[net_arg]
    fun_net(conn_os, links) # for dynamic flow rules

def virtual_delete(virt_file):
    conn_os = cloud_manager.connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    vtopo = VirtualTopology(virt_file, conn_os)
    
    for vm in vtopo.get_vms():
        print "Debug: deleting VM(%s)..."%(str(vm))
        cloud_manager.delete_vm(conn_os, vm.name)
        print "Debug: VM(%s) deleted."%(str(vm))

VM_PLACEMENT_ALGORITHMS= {
    "mff" : get_hostmap_most_full,
    "topo" : get_hostmap_topo_aware
}

NETWORK_MANAGEMENT_ALGORITHMS= {
    "df" : set_dynamic_flows
    ,"bw" : set_bandwidth_flows
    #,"df_bw" : set_dynamic_bandwidth_flows
}


def test_vm_placement():
    conn_os = cloud_manager.connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    vtopo = VirtualTopology("vm_wiki_complex.json", conn_os)
    
    vms = vtopo.get_vms()
    placed_vms, new_vms = get_vms_placed(conn_os, vms)
    
    new_vms.sort(key=lambda x: x.cores, reverse=True)
    
    links = vtopo.get_links()
    
    print vms
    print links
    
    print "mff:%s"%(str( get_hostmap_most_full(conn_os, new_vms, placed_vms = placed_vms)))
    print "topo:%s"%(get_hostmap_topo_aware(conn_os, new_vms, placed_vms = placed_vms))
    
    print "mff:%s"%(str( get_hostmap_most_full(conn_os, vms, None)))
    print "topo:%s"%(get_hostmap_topo_aware(conn_os, vms, None))
    
    #set_dynamic_flows(conn_os, links) # for dynamic flow rules
    #set_bandwidth_flows(conn_os, links) # for QoS bandwidth guarantee rules
    
    #network_defpath.set_default_paths()


def test_vm_deletion():
    conn_os = cloud_manager.connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    vtopo = VirtualTopology("test.json", conn_os)
    
    for vm in vtopo.get_vms():
        print "Debug: deleting VM(%s)..."%(str(vm))
        cloud_manager.delete_vm(conn_os, vm.name)
        print "Debug: VM(%s) deleted."%(str(vm))

# Main
def _print_usage():
    print("Usage:\t python %s test-create : test VM creation using 'test.json' file"%(sys.argv[0]))
    print("      \t python %s test-delete : delete the testing VMs defined in 'test.json' "%(sys.argv[0]))
    print("      \t python %s deploy <vm_policy> <net_policy> <virtual.json> ... : deploy VMs and networks from <virtual.json> file "%(sys.argv[0]))
    print("      \t python %s deploy-sim <vm_policy> <virtual.json> ... : simulate VM deployment"%(sys.argv[0]))
    print("      \t python %s deploy-net <net_policy> <virtual.json> ... : deploy only networks from <virtual.json> file "%(sys.argv[0]))
    print("      \t\t\t <vm_policy> : mff (Most full first) or topo (Topology-aware)")
    print("      \t\t\t <net_policy>: none (No policy) df (Dynamic flow re-routing) or bw (Bandwidth allocation)")
    print("      \t python %s delete <virtual.json> : delete deployed VMs and networks with <virtual.json> file "%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
        
    if sys.argv[1] == "test-create":
        test_vm_placement()
    elif sys.argv[1] == "test-delete":
        test_vm_deletion()
    elif sys.argv[1] == "deploy":
        vm_policy = sys.argv[2]
        net_policy = sys.argv[3]
        virt_jsons = sys.argv[4:]
        virtual_deploy(virt_jsons, vm_policy, net_policy)
    elif sys.argv[1] == "deploy-sim":
        vm_policy = sys.argv[2]
        net_policy = None
        virt_jsons = sys.argv[3:]
        virtual_deploy(virt_jsons, vm_policy, net_policy, simulate=True)
    elif sys.argv[1] == "deploy-net":
        vm_policy = None
        net_policy = sys.argv[2]
        virt_jsons = sys.argv[3:]
        virtual_deploy(virt_jsons, vm_policy, net_policy, net_only=True)
    elif sys.argv[1] == "delete":
        virtual_delete(sys.argv[2])
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()

