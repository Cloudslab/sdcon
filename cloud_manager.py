#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys
from openstack import connection as openstack_connection

import sdcon_config

class NetworkType:
    Internal = 'fixed'
    Floating = 'floating'

def connect_openstack(auth_url, auth_id, auth_pw):
    auth_args = {
        'auth_url': auth_url,
        'username': auth_id,
        'password': auth_pw,
        'project_name': 'admin',
        'user_domain_name': 'default',
        'project_domain_name': 'default',
    }
    conn_os = openstack_connection.Connection(**auth_args)
    
    # for testing only
    '''
    for network in conn_os.network.networks():
        print(network)  
        '''
    return conn_os

def create_vm(conn_os, vm_name, image_name, flavor_name, network_name,
        host_name, key_name = None, wait_time=1):
    print("Creating VM:"+ vm_name+ ", in host:"+host_name)
    
    image = conn_os.compute.find_image(image_name)
    flavor = conn_os.compute.find_flavor(flavor_name)
    network = conn_os.network.find_network(network_name)
    #keypair = create_keypair(conn_os)
    
    if image is None:
        raise LookupError("Cannot find this image: "+str(image_name))
    if flavor is None:
        raise LookupError("Cannot find this flavor: "+str(flavor_name))
    if network is None:
        raise LookupError("Cannot find this network: "+str(network_name))
    
    args = {
        'name':vm_name, 
        'image_id':image.id, 
        'flavor_id':flavor.id,
        'networks':[{"uuid": network.id}],
        'availability_zone':"nova:"+host_name}
    if key_name:
        args['key_name'] = key_name
    
    server = conn_os.compute.create_server(**args)
    try:
        server = conn_os.compute.wait_for_server(server, interval=1, wait=wait_time)
    except:
        print "Debug: compute.wait_for_server() time out"
    
    print("ssh root@{ip}".format(ip=server.access_ipv4))
    return server

def delete_vm(conn_os, vm_name):
    server = get_vm(conn_os, vm_name)
    if server:
        conn_os.compute.delete_server(server)

def get_vm(conn_os, vm_name):
    server = conn_os.compute.find_server(vm_name)
    if server != None:
        server = conn_os.compute.wait_for_server(server)
    return server

def migrate_vm(conn_os, vm_name, host_name):
    server = get_vm(conn_os, vm_name)
    if server:
        conn_os.compute.live_migrate_server(server, host=host_name)

def get_vm_hostname(conn_os, vm_name):
    server = get_vm(conn_os, vm_name)
    return server.hypervisor_hostname 

def get_vm_ip(conn_os, vm_name, type = NetworkType.Internal):
    server = get_vm(conn_os, vm_name)
    if server != None:
        for addr in server.addresses.values()[0]:
            if addr['OS-EXT-IPS:type']==type:
                return addr['addr']
    return None

def find_vm_from_ip(conn_os, vm_ip):
    for server in conn_os.compute.servers():
        for addrs in server.addresses.values():
            for addr in addrs:
                if vm_ip == addr["addr"]:
                    server = conn_os.compute.wait_for_server(server)
                    return server
    return None

def get_host(conn_os, host_name):
    # https://github.com/openstack/python-openstacksdk/blob/4bad718783ccd760cac0a97ce194f391c3ac63c5/openstack/compute/v2/hypervisor.py
    hyper = conn_os.compute.find_hypervisor(host_name)
    if hyper:
        hyper = conn_os.compute.get_hypervisor(hyper)
    return hyper

def get_host_ip_of_vm_ip(conn_os, vm_ip):
    vm = find_vm_from_ip(conn_os, vm_ip)
    if vm:
        host_name = vm.hypervisor_hostname
        return sdcon_config.hostname_to_ip(host_name)
    return None

def get_all_hosts(conn_os):
    all_hosts = []
    for hyper in conn_os.compute.hypervisors():
        hyper = conn_os.compute.get_hypervisor(hyper)
        if hyper.status=="enabled" and hyper.state == "up":
            all_hosts.append(hyper)
    all_hosts.sort(key=lambda x: x.name)
    return all_hosts

# This funtion returns the number of (total, used) vCPUs of the compute node.
def get_host_memory(conn_os, host_name):
    host = get_host(conn_os, host_name)
    if host:
        return (host.memory_size, host.memory_used)
    return (None, None)

# This funtion returns (total, used) memory of the compute node.
def get_host_vcpus(conn_os, host_name):
    host = get_host(conn_os, host_name)
    if host:
        return (host.vcpus, host.vcpus_used)
    return (None, None)

def get_flavor(conn_os, min_cpu, min_memory):
    pos_flv = []
    for flv in conn_os.compute.flavors():
        if flv.vcpus >= min_cpu and flv.ram >= min_memory:
            pos_flv.append( (flv.vcpus, flv.ram, flv) )
    pos_flv.sort()
    return pos_flv[0][2]

# This returns (cpu, memory) of the flavor
def get_flavor_cpu_memory(conn_os, flavor_name):
    flv = conn_os.compute.find_flavor(flavor_name)
    if flv:
        flv2 = conn_os.compute.get_flavor(flv)
        return (flv2.vcpus, flv2.ram)
    return (None, None)

def host_to_str(host):
    return "{host_name:%s, used_cpu:'%s/%s', used_memory:'%s/%s'}"%(
        host.name,
        str(host.vcpus_used), str(host.vcpus),
        str(host.memory_used), str(host.memory_size))

def print_host_list():
    conn_os = connect_openstack(sdcon_config.OPENSTACK_AUTH_URL,
        sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    for host in get_all_hosts(conn_os):
        print host_to_str(host)

def test_create_vm():
    conn_os = connect_openstack(sdcon_config.OPENSTACK_AUTH_URL,
        sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    
    SERVER_NAME="Jay-Test0001"
    IMAGE_NAME = "CirrOS"
    FLAVOR_NAME = "m1.nano"
    NETWORK_NAME = "admin-private"
    
    server=create_vm(conn_os, SERVER_NAME, IMAGE_NAME, FLAVOR_NAME, NETWORK_NAME, "compute5")

# Nova modules
import novaclient
import keystoneauth1

def connect_nova(auth_url, auth_id, auth_pw):
    loader = keystoneauth1.loading.get_plugin_loader('password')
    auth = loader.load_from_options(auth_url=auth_url,
                                    username=auth_id,
                                    password=auth_pw,
                                    project_name='admin',
                                    user_domain_name = 'default',
                                    project_domain_name= 'default')
    sess = keystoneauth1.session.Session(auth=auth)
    conn_nova = novaclient.client.Client(VERSION, session=sess)
    return conn_nova


def test_conn():
    conn_os = connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    for server in conn_os.compute.servers():
        print(server)
    
    for image in conn_os.compute.images():
        print(image)
    
    for flavor in conn_os.compute.flavors():
        print(flavor)
    
    for network in conn_os.network.networks():
        print(network)
    
    conn_nova = connect_nova(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)
    
# Main
def _print_usage():
    print("Usage:\t python %s test-nova : test Nova module (VM creation/retrieve) "%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
    
    test_host_name = "compute4"
    test_vm_name = "pisdc-experiment"
        
    if sys.argv[1] == "test-nova":
        test_conn()
    elif sys.argv[1] == "host-list":
        print_host_list()
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()

