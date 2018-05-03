#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import requests, json
from requests.auth import HTTPBasicAuth

############################################################
# Authentication configuration
ODL_CONTROLLER_URL = "http://url.of.odl.controller:8181" 
ODL_CONTROLLER_ID = "admin_id_odl"
ODL_CONTROLLER_PW = "admin_pw_odl"

OPENSTACK_AUTH_URL = "http://url.of.openstack.controller:5000/v3"
OPENSTACK_AUTH_ADMIN_ID = "admin_id_openstack"
OPENSTACK_AUTH_ADMIN_PW = "admin_pw_openstack"

SFLOW_COLLECTOR_URL = "http://url.of.sflow-rt.collector"
#
############################################################

class SDCNodeIdType():
    Core=1029  #4096000x 
    Aggr=1027  #4096001x
    Edge=1024  #4096002x
    Mac =513 #ab:cd:ef:11:22:33
    Ip  =512 #ab:cd:ef:11:22:33
    
    @staticmethod
    def get_type(id):
        type=None
        if len(id.split(":")) == 6:
            type= SDCNodeIdType.Mac
        elif len(id.split(".")) == 4:
            type= SDCNodeIdType.Ip
        else:
            if id[-2] == '0':
                type= SDCNodeIdType.Core
            elif id[-2] == '1':
                type= SDCNodeIdType.Aggr
            elif id[-2] == '2':
                type= SDCNodeIdType.Edge
        return type
    
    @staticmethod
    def is_switch(id):
        type= SDCNodeIdType.get_type(id)
        if type==SDCNodeIdType.Edge or type==SDCNodeIdType.Aggr or type==SDCNodeIdType.Core:
            return True
        return False
    
    @staticmethod
    def is_host(id):
        type=SDCNodeIdType.get_type(id)
        if type==SDCNodeIdType.Mac or type==SDCNodeIdType.Ip:
            return True
        return False


def hostname_to_ip(host_name):
    host_id = host_name.replace("compute","")
    host_ip = "192.168.0."+host_id
    return host_ip

def ip_to_hostname(host_ip):
    host_id = host_ip.split(".")[-1]
    host_name = "compute"+host_id
    return host_name

# Checks if IP address is a switch or not.
def is_ip_switch(ip):
    if 100<=int(ip.split(".")[-1])<=130:
        return True
    return False

# Converts switch's IP address to DPID to use in ODL
def switch_ip_to_dpid(ip_addr):
    # 192.168.99.1AB -> 409600AB
    if ip_addr == "ALL":
        return ip_addr
    elif not is_ip_switch(ip_addr):
        new_ip=ip_addr.split(".")
        new_ip[2]="0"
        return ".".join(new_ip)
    return "409600"+ip_addr[-2:]

# Converts switch's DPID to IP address
def switch_dpid_to_ip(dpid):
    # 409600AB -> 192.168.99.1AB
    if dpid == "ALL":
        return dpid
    if SDCNodeIdType.is_switch(dpid):        
        return "192.168.99.1"+dpid[-2:]
    return dpid


def data_source_to_port(switch_dpid, data_source):
    if SDCNodeIdType.is_switch(switch_dpid):
        return str(int(data_source)-2)
    return str(data_source)

def port_to_data_source(switch_dpid, port):
    if SDCNodeIdType.is_switch(switch_dpid):
        return str(int(port)+2) 
    return str(port) 


def __get_all_port_info_raw(base_url, id, pw, switch):
    #Debug: ODL_CONTROLLER_URL/restconf/operational/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:40960000%2Fbridge%2Fovsbr0/
    url = base_url + '/restconf/operational/network-topology:network-topology/topology/ovsdb:1/node/ovsdb:'+str(switch)+'%2Fbridge%2Fovsbr0'
    response = requests.get(url, auth=HTTPBasicAuth(id, pw), \
        headers={"Accept": "application/json"})
    if response.status_code != 200:
        print "!!!WARNING!!! verify_oper_bind_port_qos_raw: %s, %s, retry:%d",(switch, ifname,i)
        response.raise_for_status()
    return response.json()

def __get_all_port_info(switch):
    br_data = __get_all_port_info_raw(ODL_CONTROLLER_URL, ODL_CONTROLLER_ID, ODL_CONTROLLER_PW, switch)
    return br_data['node'][0]['termination-point']

def port_to_ifname(switch, port_no):
    print "Debug: prot to ifname ",switch, port_no
    for port in __get_all_port_info(switch):
        if ('ovsdb:ofport' in port) and (str(port['ovsdb:ofport']) == str(port_no)):
            return port['tp-id']

def port_to_ifindex(switch, port_no):
    for port in __get_all_port_info(switch):
        if str(port['ovsdb:ofport']) == str(port_no):
            return port['ovsdb:ifindex']

def ifname_to_ofport(switch, ifname):
    for port in __get_all_port_info(switch):
        if str(port['tp-id']) == str(ifname):
            return str(port['ovsdb:ofport'])
