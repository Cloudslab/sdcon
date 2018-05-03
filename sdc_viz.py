#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import networkx
import json, time
import flask
import sys
from networkx.readwrite import json_graph

import topo_discovery, network_monitor, cloud_monitor
from sdcon_config import SDCNodeIdType

MAX_BYTES_PER_SEC = 95000000 / 8 # 95Mbits/sec = 11.875 MBytes/sec

LINE_WIDTH_MIN=1
LINE_WIDTH_MAX=10

GRAPH_BW_THRESHOLD = 1000 #(1 KByetes/s)

DATA_UPDATE_INTERVAL_HOST = 60 

last_updated_host = 0
LIST_HOST_IP = ["192.168.0."+str(i) for i in range(1,10)]
host_cpu_util={}

def get_host_util(host_ip):
    global last_updated_host, host_cpu_util
    current_time = time.time()
    if current_time - last_updated_host > DATA_UPDATE_INTERVAL_HOST:
        for host_ip in LIST_HOST_IP:
            host_cpu_util[host_ip] = retrieve_host_cpu_util(host_ip)
    
    return host_cpu_util[host_ip]

conn_gnocchi = cloud_monitor.connect_gnocchi()
def retrieve_host_cpu_util(host_ip):
    global conn_gnocchi
    host = sdcon_config.ip_to_hostname(host_ip)
    try:
        all_measurements = cloud_monitor.host_utilization_all(conn_gnocchi, hostname=host)
    except:
        conn_gnocchi = cloud_monitor.connect_gnocchi()
        all_measurements = cloud_monitor.host_utilization_all(conn_gnocchi, hostname=host)
    return float(all_measurements[-1][2])/100


def bw_to_width(bw):
    return bw * (LINE_WIDTH_MAX-LINE_WIDTH_MIN) / MAX_BYTES_PER_SEC + LINE_WIDTH_MIN

def node_to_type(node):
    if SDCNodeIdType.is_host(node):
        return 1
    return 2

def get_fixed_pos_index(node):
    x_index = float(node[-1])
    y_index = float(node[-2])
    return x_index, y_index

SCREEN_FULLSIZE_X = 960
SCREEN_FULLSIZE_Y = 700
SCREEN_MARGIN_LEFT = 120
SCREEN_MARGIN_TOP = 100
SCREEN_SIZE_X = SCREEN_FULLSIZE_X - 2*SCREEN_MARGIN_LEFT
SCREEN_SIZE_Y = SCREEN_FULLSIZE_Y - 2*SCREEN_MARGIN_TOP

MAX_TIER = 3
MAX_HORIZONTAL_SWITCHES = 4

def get_fixed_pos(node):
    if SDCNodeIdType.is_host(node):
        return None
    x_index, y_index = get_fixed_pos_index(node)
    if y_index == 0:
        x_index = float(x_index)*(MAX_HORIZONTAL_SWITCHES/2) + 0.5
    x = (x_index+ 0.5) / MAX_HORIZONTAL_SWITCHES 
    y = (y_index+ 0.5) / MAX_TIER
    return int(SCREEN_SIZE_X*x)+SCREEN_MARGIN_LEFT, int(SCREEN_SIZE_Y*y)+SCREEN_MARGIN_TOP

def get_flowkey_hash(src_dst):
    src_ip = src_dst.split(",")[0]
    dst_ip = src_dst.split(",")[1]
    seed1 = int (src_ip.split(".")[-1])
    seed2 = int (dst_ip.split(".")[-1])
    val = min(seed1,seed2)*10+max(seed1,seed2) # 12~89
    if val > 50:
        val = 100 - val # 11~49
    return val


def get_data_base(topo, flow_name):
    g = topo.topo_graph.to_directed()
    for node in networkx.nodes(g):
        g.add_node(node, type = node_to_type(node))
        g.add_node(node, label = topo.get_host_ip(node))
        if SDCNodeIdType.is_switch(node):
            fx, fy = get_fixed_pos(node)
            g.add_node(node, fx = fx, fy = fy)
        else:
            g.add_node(node, y=SCREEN_SIZE_Y, x=SCREEN_SIZE_X/2)

    bw_usage = network_monitor.get_bw_usage_all_incoming(flow_name = flow_name)
    for this_node in bw_usage:
        if SDCNodeIdType.is_host(this_node):
            this_switch = topo.get_host_mac(this_node)
        else:
            this_switch = this_node
        if this_switch == None:
            continue
        #print this_node, bw_usage[this_node]
        for this_inport, bw in bw_usage[this_node]:
            other_switch = topo.get_connected_node_via_port(this_switch, this_inport)
            if other_switch and this_switch:
                #print "Viz: %s -> %s : %s"%(other_switch,this_switch,str(bw))
                g[other_switch][this_switch]['weight']=bw
                g[other_switch][this_switch]['width'] = bw_to_width(bw)
    return json_graph.node_link_data(g)

def get_data_extra(topo, flow_name):
    extra_path = []
    bw_usage = network_monitor.get_bw_usage_all_link_flows(flow_name = flow_name)
    for this_node in bw_usage:
        if SDCNodeIdType.is_host(this_node):
            this_switch = topo.get_host_mac(this_node)
        else:
            this_switch = this_node
        #print "Debug for bw usage:",this_node, bw_usage[this_node]
        for this_inport, flow_bw_pair in bw_usage[this_node]:
            # flow_bw_pair = [ (srcdst1, bw1), (srcdst2, bw2), ... ]
            other_switch = topo.get_connected_node_via_port(this_switch, this_inport)
            if other_switch and this_switch:
                #print "Viz: %s -> %s : "%(other_switch,this_switch), flow_bw_pair
                for flowkey, bw_val in flow_bw_pair:
                    if bw_val > GRAPH_BW_THRESHOLD:
                        extra_path.append( {
                            "source":other_switch, 
                            "target":this_switch, 
                            "bw": int(bw_val),
                            "width": bw_to_width(bw_val),
                            "addr": flowkey,
                            "value": get_flowkey_hash(flowkey) } )
    return extra_path

def __get_data(flow_name = network_monitor.SFLOW_FLOW_NORMAL):
    topo = topo_discovery.SDCTopo(sdcon_config.ODL_CONTROLLER_URL, sdcon_config.ODL_CONTROLLER_ID, sdcon_config.ODL_CONTROLLER_PW)
    
    basic = get_data_base(topo, flow_name)
    extra = get_data_extra(topo, flow_name)
    basic["links2"] = extra
    
    return json.dumps(basic, indent=4)

DATA_UPDATE_INTERVAL = 0.5 # update monitored data at every 0.5 sec

last_update_time = 0
last_update_data = None
def update_data():
    global last_update_time, last_update_data
    current_time = time.time()
    if current_time - last_update_time > DATA_UPDATE_INTERVAL:
        last_update_time = current_time
        last_update_data = __get_data()
    return last_update_data

def get_data():
    return update_data()


last_update_time_vm = 0
last_update_data_vm = None
def update_data_vm():
    global last_update_time_vm, last_update_data_vm
    current_time = time.time()
    if current_time - last_update_time_vm > DATA_UPDATE_INTERVAL:
        last_update_time_vm = current_time
        last_update_data_vm = __get_data(network_monitor.SFLOW_FLOW_TUNNEL)
    return last_update_data_vm

def get_data_vm():
    return update_data_vm()

app = flask.Flask(__name__, static_folder="sdc_viz_html")

@app.route('/about')
def about():
    return 'The about page'

@app.route('/sdc_viz_data')
def data():
    return get_data()

@app.route('/sdc_viz_data_vm')
def data_vm():
    return get_data_vm()

@app.route('/')
def static_root():
    return static_index()

@app.route('/index.html')
def static_index():
    return app.send_static_file('index.html')

@app.route('/dev')
def static_dev():
    return app.send_static_file('dev.html')

@app.route('/test_data.json')
def static_test_data():
    return app.send_static_file('test_data.json')

# Main
def main():
    portNum = 8000
    if len(sys.argv) > 1:
        portNum = int(sys.argv[1])
    
    network_monitor.start_monitor()
    print get_data()
    print get_data_vm()
    app.run( port=portNum, host="0.0.0.0" )

if __name__ == '__main__':
    main()