#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys
import requests
from time import sleep
from requests.auth import HTTPBasicAuth
from collections import defaultdict
import network_manager, topo_discovery, sdcon_config

NETWORK_MAX_BW_RATE=95000000 # bits per sec. 95Mbps
DEFAULT_MIN_BW_RATIO = 0.1  

class SDCQueues:
    def __init__(self, toal_rate):
        self.min_bw={}
        self.max_bw={}
        self.fixed_path={}
        self.toal_rate = toal_rate
        self.__init_qos_config()
    
    def add_qos_bw(self, src_ip, dst_ip, min_bw_bps, max_bw_bps, path=None):
        self.min_bw[(src_ip, dst_ip)] = min_bw_bps
        self.max_bw[(src_ip, dst_ip)] = max_bw_bps
        if path:
            self.fixed_path[(src_ip, dst_ip)] = path
    
    def del_qos_bw(self, src_ip, dst_ip):
        del self.min_bw[(src_ip, dst_ip)]
        del self.max_bw[(src_ip, dst_ip)]
    
    def get_qos_minbw(self, src_ip, dst_ip):
        return self.min_bw[(src_ip, dst_ip)]
    
    def get_qos_maxbw(self, src_ip, dst_ip):
        return self.max_bw[(src_ip, dst_ip)]
    
    def __init_qos_config(self):
        self.switch_q = defaultdict(list) # dict[switch] = List of (outport, src_ip, dst_ip, bw)
        self.switch_qindex = defaultdict(dict) # dict[switch][(src,dst)] = index of queue in switch_q
        self.switch_qcfg = {} # dict[switch][port] = list of queue_cfg
        self.switch_port_fl = {} # dict[switch][port] = list of [(src,dst), ..]
    
    def __build_queue_along_path(self, topo, path, src_ip, dst_ip):
        for (inport, switch, outport) in topo.get_switch_port_map(path):
            self.switch_qindex[switch][(src_ip, dst_ip)] = len(self.switch_q[switch])
            self.switch_q[switch].append( (outport, src_ip, dst_ip) )
    
    def __build_queue_config(self):
        self.switch_qcfg = {}
        self.switch_port_fl = {}
        for switch in self.switch_q:
            port_queue_cfg = defaultdict(list)
            port_fl = defaultdict(list)
            # Add queue configs to each port
            for (outport, src_ip, dst_ip) in self.switch_q[switch]:
                port_queue_cfg[outport].append({
                    "no": self.get_queue_no(switch, src_ip, dst_ip),
                    "min-rate":self.get_qos_minbw(src_ip, dst_ip), 
                    "max-rate":self.get_qos_maxbw(src_ip, dst_ip)} )
                port_fl[outport].append( (src_ip, dst_ip) )
            self.switch_qcfg[switch] = port_queue_cfg
            self.switch_port_fl[switch] = port_fl
    
    def build_qos_config(self, topo, func_get_path = None):
        if func_get_path == None:
            func_get_path = network_manager.get_default_path
        self.__init_qos_config()
        for (src_ip, dst_ip) in self.min_bw:
            print "Debug: finding a path for %s->%s"%(src_ip, dst_ip)
            # Get a path to install the qos queue
            if (src_ip, dst_ip) in self.fixed_path and self.fixed_path[(src_ip, dst_ip)]:
                path = self.fixed_path[(src_ip, dst_ip)]
            else:
                path = func_get_path(topo, src_ip, dst_ip)
            print "Build queue settings (%s->%s) for path:%s"%(src_ip, dst_ip, path)
            self.__build_queue_along_path(topo, path, src_ip, dst_ip)
        # After all pairs are added, build
        self.__build_queue_config()
    
    def get_queue_no(self, switch, src_ip, dst_ip):
        if (src_ip, dst_ip) in self.switch_qindex[switch]:
            return self.switch_qindex[switch][(src_ip, dst_ip)]+10
        
        print "get_queue_no: no queue.", switch, src_ip, dst_ip
        return None
    
    def get_queue_cfg(self, switch, port):
        return self.switch_qcfg[switch][port]
    
    def get_switches(self):
        return self.switch_qcfg.keys()
    
    def get_switch_ports(self, switch):
        return self.switch_qcfg[switch].keys()
    
    def get_qos_config_dump(self):
        return self.switch_qcfg
    
    def add_flow_rule(self, switch, port, src_ip, dst_ip):
        add_flow_enqueue(switch, port, self.get_queue_no(switch, src_ip, dst_ip),  src_ip, dst_ip)
    
    # This function creates QoS and Queues in OVSDB, and adds flow rules in forwarding table.
    # 1. 
    def install_all_queue_flow(self):
        for switch in self.get_switches():
            print "Installing flows for switch: "+str(switch)
            set_queue(switch, self.switch_qcfg[switch], self.toal_rate)
            for port in self.get_switch_ports(switch):
                for (src_ip, dst_ip) in self.switch_port_fl[switch][port]:
                    self.add_flow_rule(switch, port, src_ip, dst_ip)
    
    def delete_all_queue_flow(self):
        for switch in self.get_switches():
            print "Deleting flows for switch: "+str(switch)
            for port in self.get_switch_ports(switch):
                for (src_ip, dst_ip) in self.switch_port_fl[switch][port]:
                    del_flow_enqueue(switch, src_ip, dst_ip)
                delete_queue_with_cfg(switch, port, self.get_queue_cfg(switch, port))

def __generate_json_set_queue_qos_entries(switch, port, queue_cfg_list, total_rate):
    qos_id = port_to_qosid(port)
    jdata = '''
                {   "qos-id": "'''+str(qos_id)+'''",
                    "qos-other-config": [
                        {   "other-config-key": "max-rate",
                            "other-config-value": "'''+str(total_rate)+'''"}],
                    "qos-type": "ovsdb:qos-type-linux-htb",
                    "queue-list": [
                        {   "queue-number": "0",
                            "queue-ref": "/network-topology:network-topology/''' \
                            +'''network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id=\'ovsdb:'''\
                            +str(switch)+'''\']/ovsdb:queues[ovsdb:queue-id='QUEUE-DEF-'''+str(port)+'''\']"
                        }'''
    for cfg in queue_cfg_list:
        jdata += '''         ,{  "queue-number": "'''+str(cfg["no"])+'''",
                            "queue-ref": "/network-topology:network-topology/''' \
                            +'''network-topology:topology[network-topology:topology-id='ovsdb:1']/network-topology:node[network-topology:node-id=\'ovsdb:'''\
                            +str(switch)+ '''\']/ovsdb:queues[ovsdb:queue-id=\'QUEUE-'''\
                            +str(cfg["no"])+'''\']"}'''
    jdata +='''          ]}'''
    return jdata

def __generate_json_set_queue_queues(queue_id, max_rate, min_rate):    
    jdata ='''    {   "queue-id": "'''+queue_id+'''",
                        "queues-other-config": [
                            {   "queue-other-config-key": "max-rate",
                                "queue-other-config-value": "'''+str(max_rate)+'''"},
                            {   "queue-other-config-key": "min-rate",
                                "queue-other-config-value": "'''+str(min_rate)+'''"}]
                    }'''
    return jdata

def __generate_json_set_queue(switch, port_queue_cfg_list, total_rate, default_min_rate, default_max_rate):
    # queue_cfg_list is list of queue configurations, which must have q-no, min-rate, max-rate.
    # queue_cfg_list = [ {"no":20,"min-rate":2000000, "max-rate":90000000}, ...]
    # This will be put into: .../restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:{{ovs-node}}
    switch_ip = sdcon_config.switch_dpid_to_ip(switch)
    
    jdata = '''{
        "network-topology:node": [
            {   "node-id": 'ovsdb:'''+str(switch)+'''',
                "connection-info": {
                    "ovsdb:remote-port": "6640",
                    "ovsdb:remote-ip": "'''+switch_ip+'''"
                  },
                "ovsdb:qos-entries": ['''
    jdata_add=[]
    for port, queue_cfg_list in port_queue_cfg_list.items():
        jdata_add.append( __generate_json_set_queue_qos_entries(switch, port, queue_cfg_list, total_rate) )
    jdata += ",".join(jdata_add)
    jdata +='''                    ],'''
    jdata +='''            "ovsdb:queues": ['''
    jdata_add=[]
    for port, queue_cfg_list in port_queue_cfg_list.items():
        #For default port.
        jdata_add.append(__generate_json_set_queue_queues("QUEUE-DEF-"+str(port), default_max_rate, default_min_rate))
        for cfg in queue_cfg_list:
            jdata_add.append(__generate_json_set_queue_queues("QUEUE-"+str(cfg["no"]), cfg['max-rate'], cfg['min-rate']))
    jdata += ",".join(jdata_add)
    jdata += ''' ] } ]}'''
    return jdata

def __generate_json_bind_port_qos(switch, port, qos_id):
    ifname = sdcon_config.port_to_ifname(switch, port)
    jdata ='''
    {"network-topology:termination-point": [
            {   "ovsdb:name": "'''+str(ifname)+'''",
                "tp-id": "'''+str(ifname)+'''",
                "ovsdb:qos-entry": [{
                        "qos-key": 1,
                        "qos-ref": "/network-topology:network-topology/network-topology:topology[network-topology'''\
                        +''':topology-id='ovsdb:1']/network-topology:node[network-topology:node-id=\'ovsdb:'''\
                        +str(switch)+'''\']/ovsdb:qos-entries[ovsdb:qos-id=\''''+str(qos_id)+'''\']"
                    }] } ]}'''
    return jdata

def push_qos_queue_raw(base_url, id, pw, switch, json_data):
    print "Creating QoS and Queues in switch:"+switch
    url = base_url + '/restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)
    response = requests.put(url, data=json_data, auth=HTTPBasicAuth(id, pw), \
        headers={"Accept":"application/json", "Content-Type":"application/json"})
    sleep(0.3)
    if response.status_code != 200 and response.status_code != 201:
        print url
        print json_data
        response.raise_for_status()

def del_qos_raw(base_url, id, pw, switch, qos_id):
    print "Deleting QoS entry %s at %s"%(qos_id, switch)
    url = base_url + '/restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'/ovsdb:qos-entries/'+str(qos_id)
    response = requests.delete(url, auth=HTTPBasicAuth(id, pw),  headers={"Accept": "application/json"})
    sleep(0.3)
    if response.status_code != 200:
        print "Error: cannot delete QoS %s at %s!"%(qos_id, switch)
        print url

def del_queue_raw(base_url, id, pw, switch, queue_no):
    print "Deleting Queue no %s at %s..."%(queue_no, switch)
    url = base_url + '/restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'/ovsdb:queues/QUEUE-'+str(queue_no)
    response = requests.delete(url, auth=HTTPBasicAuth(id, pw),  headers={"Accept": "application/json"})
    sleep(0.3)
    if response.status_code != 200:
        print "Error: cannot delete Queue %s at %s!"%(queue_no, switch)
        print url

def push_bind_port_qos_raw(base_url, id, pw, switch, ifname, json_data):
    url = base_url + '/restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'%2Fbridge%2Fovsbr0/termination-point/'+str(ifname)
    response = requests.put(url, data=json_data, auth=HTTPBasicAuth(id, pw), \
        headers={"Accept":"application/json", "Content-Type":"application/json"})
    sleep(0.3)
    if response.status_code != 200 and response.status_code != 201:
        print url
        print json_data
        response.raise_for_status()

def del_bind_port_qos_raw(base_url, id, pw, switch, ifname, qos_id):
    print "Deleting port binding %s-%s at %s"%(ifname, qos_id, switch)
    url = base_url +'/restconf/config/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'%2Fbridge%2Fovsbr0/termination-point/'+str(ifname)+'/qos-entry/'+"1"
    response = requests.delete(url, auth=HTTPBasicAuth(id, pw),  headers={"Accept": "application/json"})
    sleep(0.3)
    if response.status_code != 200:
        print "Error: cannot delete QoS %s attached at %s-%s!"%(qos_id, ifname, switch)
        print url

def verify_oper_qos_raw(base_url, id, pw, switch, qos_id):
    url = base_url + '/restconf/operational/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'/ovsdb:qos-entries/'+str(qos_id)
    for i in range(5):
        response = requests.get(url, auth=HTTPBasicAuth(id, pw), \
            headers={"Accept": "application/json"})
        if response.status_code == 200:
            break
        else:
            print "!!!WARNING!!! verify_oper_qos_raw: %s, %s, retry:%d",(switch, qos_id,i)
            sleep(1)
    if i == 4:
        print "!!!ERROR!!! QoS is not properly set. Exit"
        response.raise_for_status()
    return response.json()

def verify_oper_bind_port_qos_raw(base_url, id, pw, switch, ifname):
    url = base_url + '/restconf/operational/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'%2Fbridge%2Fovsbr0/termination-point/'+str(ifname)
    for i in range(5):
        response = requests.get(url, auth=HTTPBasicAuth(id, pw), \
            headers={"Accept": "application/json"})
        if response.status_code == 200:
            break
        else:
            print "!!!WARNING!!! verify_oper_bind_port_qos_raw: %s, %s, retry:%d",(switch, ifname,i)
            sleep(1)
    if i == 4:
        print "!!!ERROR!!! Port bind is not properly set. Exit"
        response.raise_for_status()
    return response.json()


def port_to_qosid(port_no):
    qos_id = "qos_port_"+str(port_no)
    #qos_id = "qos"+str(port_no)
    return qos_id    

def bind_port_qos(switch, port, qos_id):
    ifname = sdcon_config.port_to_ifname(switch, port)
    jdata = __generate_json_bind_port_qos(switch, port, qos_id)
    print "Binding port.. %s -- %s at %s"%(ifname, qos_id, switch)
    #print "Debug:",jdata
    push_bind_port_qos_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, ifname, jdata)

def unbind_port_qos(switch, port, qos_id):
    ifname = sdcon_config.port_to_ifname(switch, port)
    print "Unbinding port.. %s -- %s at %s"%(ifname, qos_id, switch)
    del_bind_port_qos_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, ifname, qos_id)

def set_queue(switch, port_queue_cfg, total_rate, def_min=None, def_max=None):
    if def_max == None:
        def_max = total_rate
    if def_min == None:
        def_min = total_rate*DEFAULT_MIN_BW_RATIO # 10%
    # Set queue
    jdata = __generate_json_set_queue(switch, port_queue_cfg, total_rate, def_min, def_max)
    push_qos_queue_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, jdata)
    # Bind a port to the queue
    for port in port_queue_cfg.keys():
        qos_id = port_to_qosid(port) 
        verify_oper_qos_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, qos_id)
        bind_port_qos(switch, port, qos_id)
        verify_oper_bind_port_qos_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, sdcon_config.port_to_ifname(switch, port))

def delete_queue(switch, port, queue_nos):
    qos_id = port_to_qosid(port)
    unbind_port_qos(switch, port, qos_id)
    
    del_qos_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, qos_id)
    for no in queue_nos:
        del_queue_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, no)
    del_queue_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, "DEF-"+str(port))

def delete_queue_with_cfg(switch, port, queue_cfg_list):
    queue_nos = []
    for cfg in queue_cfg_list:
        queue_nos.append( cfg["no"] )
    delete_queue(switch, port, queue_nos)

def add_flow_enqueue(switch, port_no, queue_no, src_ip, dst_ip):
    network_manager.add_flow(switch, str(port_no), network_manager.ODL_FLOW_PRIORITY_SPECIAL_PATH_QUEUE, 
        action_queue=str(queue_no), match_src_ip=src_ip, match_dst_ip=dst_ip, table_id=0, flowname = network_manager.FLOWNAME_SPECIAL_QUEUE)

def del_flow_enqueue(switch, src_ip=None, dst_ip=None):
    table_id="0"
    flows = network_manager.get_flows(switch, table_id)
    for fl in flows:
        if network_manager.FLOWNAME_SPECIAL_QUEUE == fl['flow-name']:
            if src_ip and dst_ip and src_ip in fl['match']['ipv4-source'] and dst_ip in fl['match']['ipv4-destination']:
                try:
                    network_manager.del_flow_raw(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW, switch, table_id, fl['id'])
                    sleep(0.3)
                except:
                    continue
    sleep(0.3)


def del_all_queue_paths(topo):
    network_manager.del_all_flows_match_name(topo, network_manager.FLOWNAME_SPECIAL_QUEUE)

def del_all_queues(topo, max_queue_no=10):
    queue_nos = range(0, max_queue_no)
    for switch, ports in topo.get_all_switches_with_port():
        for port in ports:
            delete_queue(switch, port, queue_nos)
    

def all_clear():
    topo = topo_discovery.SDCTopo(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW)
    # Clear flows from forwarding tables
    del_all_queue_paths(topo)
    # Clear Queue settings from 
    del_all_queues(topo)

QOS_QUEUE = SDCQueues(NETWORK_MAX_BW_RATE)

def add_entry(src_ip, dst_ip, min_bw, max_bw=NETWORK_MAX_BW_RATE):
    QOS_QUEUE.add_qos_bw(src_ip, dst_ip, min_bw, max_bw)

def apply_qos():
    topo = topo_discovery.SDCTopo(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW)
    QOS_QUEUE.build_qos_config(topo)
    print "Queue configs..."
    print QOS_QUEUE.get_qos_config_dump()
    QOS_QUEUE.install_all_queue_flow()

def delete_qos():
    QOS_QUEUE.delete_all_queue_flow()

def test_queue_manager(is_create):
    topo = topo_discovery.SDCTopo(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW)
    
    toal_rate=NETWORK_MAX_BW_RATE
    
    QOS_QUEUE.add_qos_bw("192.168.0.4", "192.168.0.6", 60000000, toal_rate)
    QOS_QUEUE.add_qos_bw("192.168.0.4", "192.168.0.7", 10000000, 20000000)
    QOS_QUEUE.add_qos_bw("192.168.0.4", "192.168.0.8", 50000000, toal_rate)
    
    QOS_QUEUE.build_qos_config(topo)
    print "Queue configs..."
    print QOS_QUEUE.get_qos_config_dump()
    print "Q-no at %s for %s -> %s: %s"%("40960021", "192.168.0.4", "192.168.0.7", str(QOS_QUEUE.get_queue_no("40960021", "192.168.0.4", "192.168.0.7")))
    print "Q-no at %s for %s -> %s: %s"%("40960022", "192.168.0.4", "192.168.0.7", str(QOS_QUEUE.get_queue_no("40960022", "192.168.0.4", "192.168.0.7")))
    
    if(is_create):
        QOS_QUEUE.install_all_queue_flow()
    else:
        QOS_QUEUE.delete_all_queue_flow()

def test_queue_single(is_create):
    switch ="40960001"
    port = 2
    
    toal_rate, def_min, def_max=95000000, 1000000, 60000000
    src_ip, dst_ip="192.168.0.5", "192.168.0.6"
    QID_LOW,QID_HIGH = 1, 2
    queue_cfg = []
    #queue_cfg.append( {"no":QID_LOW,"min-rate":0, "max-rate":90000000} )
    queue_cfg.append( {"no":QID_HIGH,"min-rate":50000000, "max-rate":90000000} )
    port_queue_cfg = {port: queue_cfg}
    
    if(is_create):
        set_queue(switch, port_queue_cfg, toal_rate, def_min, def_max)
        add_flow_enqueue(switch, port, QID_HIGH, src_ip, dst_ip)
    else:
        del_flow_enqueue(switch, src_ip, dst_ip)
        delete_queue_with_cfg(switch, port, queue_cfg)

# Main
def _print_usage():
    print("Usage:\t python %s test-set \t- creating a test queue"%(sys.argv[0]))
    print("      \t python %s test-del \t- delete the test queue"%(sys.argv[0]))
    print("      \t python %s clear \t- clears all queue flows from forwarding table and QoS and Queue settings from OVS"%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
    
    if sys.argv[1] == "test-set":
        test_queue_manager(True)
    elif sys.argv[1] == "test-del":
        test_queue_manager(False)
    elif sys.argv[1] == "test-single-set":
        test_queue_single(True)
    elif sys.argv[1] == "test-single-del":
        test_queue_single(False)
    elif sys.argv[1] == "clear":
        all_clear()        
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()
