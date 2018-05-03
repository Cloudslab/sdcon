#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys
# Gnocchi modules
from keystoneauth1 import loading
from gnocchiclient.v1 import client
from oslo_config import cfg
from datetime import datetime

MONITOR_NUM_POINTS=6 #5 mins x 6 = 30 mins

def connect_gnocchi():
    conf = cfg.ConfigOpts()
    loading.register_auth_conf_options(conf, "keystone_authtoken")
    loading.register_session_conf_options(
            conf, "keystone_authtoken",
            deprecated_opts={'cacert': [
                cfg.DeprecatedOpt('os-cacert', group="keystone_authtoken"),
                cfg.DeprecatedOpt('os-cacert', group="DEFAULT")]
            })
    conf([], project='gnocchi')     
    
    auth_plugin = loading.load_auth_from_conf_options(conf, "keystone_authtoken")
    conn_gnocchi = client.Client(session_options={'auth': auth_plugin})
    return conn_gnocchi

def _get_measure_mean(conn_gnocchi, metric, resource_id, num_points=MONITOR_NUM_POINTS):
    measures = conn_gnocchi.metric.get_measures(metric, resource_id=resource_id)
    # for debug
    print("Debug: _get_measure_mean(%s, %s): from %s to %s"%(metric, resource_id, measures[-1*num_points][0], measures[-1][0]))
    # find mean values
    total_m = 0
    for m in measures[-1*num_points:]:
        total_m += m[2]
    return total_m/num_points

def _get_host_resource_id(conn_gnocchi, hostname):
    # find a compute node in the list
    hostname = "compute."+hostname
    for rsrc in conn_gnocchi.resource.list("nova_compute"):
        if rsrc["host_name"] == hostname:
            return rsrc["id"]
    return None

def _get_host_name(conn_gnocchi, resource_id):
    for rsrc in conn_gnocchi.resource.list("nova_compute"):
        if rsrc["id"] == resource_id:
            return rsrc["host_name"].split(".",1)[1]

def get_all_host_resource_id(conn_gnocchi):
    resource_ids = []
    for rsrc in conn_gnocchi.resource.list("nova_compute"):
        resource_ids.append(rsrc["id"])
    return resource_ids

def host_utilization(conn_gnocchi, hostname=None, hostid=None):
    if hostid == None:
        hostid = _get_host_resource_id(conn_gnocchi, hostname)
    cpu_util = _get_measure_mean(conn_gnocchi, "compute.node.cpu.percent", hostid)
    return cpu_util/100

def host_utilization_all(conn_gnocchi, hostname=None, hostid=None):
    # returns the list of measurement. [ [u'2017-12-01T07:21:00+00:00', 60.0, 34.0], ...]
    # ret[n][0]: UTC time, [1]: Time interval between measurement, [2]: measurement
    if hostid == None:
        hostid = _get_host_resource_id(conn_gnocchi, hostname)
    measures = conn_gnocchi.metric.get_measures("compute.node.cpu.percent", resource_id=hostid)
    return measures

def _get_vm_resource_id(conn_gnocchi, vmname):
    for rsrc in conn_gnocchi.resource.list("instance"):
        if rsrc["display_name"] == vmname and rsrc["ended_at"] ==None:
            return rsrc["id"]
    return None

def vm_utilization(vmname, conn_gnocchi):
    vmid = _get_vm_resource_id(conn_gnocchi, vmname)
    cpu_util = _get_measure_mean(conn_gnocchi, "cpu_util", vmid)
    return cpu_util

def test_gnocchi(host_name, vm_name):
    conn_gnocchi=connect_gnocchi()
    hostid=_get_host_resource_id(conn_gnocchi, host_name)
    
    print "Getting host ID of a compute node: %s = %s"%(host_name, hostid)
    #print conn_gnocchi.resource.list("generic")
    print "Current time (UTC) =", datetime.utcnow()
    
    print "\nLast 5 host CPU utilizations:"
    print conn_gnocchi.metric.get_measures("compute.node.cpu.percent", resource_id=hostid)[-5:]
    util = host_utilization(conn_gnocchi, host_name)
    print "Average host utilization: of (%s) = %s\n"%(host_name, util)
    
    print "VM utilization of (%s): %s"%(vm_name, str(vm_utilization(vm_name, conn_gnocchi)))
    
    print "All hosts utilization"
    for host_id in get_all_host_resource_id(conn_gnocchi):
        name = _get_host_name(conn_gnocchi, host_id)
        util = host_utilization(conn_gnocchi, hostid=host_id)
        print "%s : %f / 1.000"%(name, util) 

# Main
def _print_usage():
    print("Usage:\t python %s test-gnocchi : test Gnocchi module (VM/hosts monitoring)"%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
    
    test_host_name = "compute4"
    test_vm_name = "pisdc-experiment"
        
    if sys.argv[1] == "test-gnocchi":
        test_gnocchi(test_host_name, test_vm_name)
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()

