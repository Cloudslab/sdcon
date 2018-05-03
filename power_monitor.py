#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
from dateutil import parser
from datetime import datetime
import time,sys
import cloud_monitor, network_manager

POWEROFF_CPU_UTIL = -0.01 # If the utilizaion is below this, the host is assumed powered off
THRESHOLD_ACTIVE_SWITCH = 10 # If the switch port transports more than this, it is assumed active.

POWER_SPEC = {     # idle_watt, working_watt_max
    "compute2": (147.0, 160.0),
    "compute3": (147.0, 160.0),
    "compute4": (111.0, 80.0),
    "compute5": (111.0, 80.0),
    "compute6": (111.0, 80.0),
    "compute7": (111.0, 80.0),
    "compute8": (102.0, 80.0),
    "compute9": (102.0, 80.0)
}


SWITCH_SPEC = {     # idle_watt, working_watt_per_port
    "all": (66.7, 1)
}
def get_current_time():
    return time.mktime(datetime.utcnow().timetuple())

def select_measurements_since(measurements, start_time, end_time):
    selected_measurements = []
    
    for measure in measurements:
        this_end_time = time.mktime(parser.parse(measure[0]).replace(tzinfo=None).timetuple())
        duration = int(measure[1])
        this_start_time = this_end_time - duration
        
        if this_start_time < end_time and this_start_time > start_time:
            selected_measurements.append(measure)
        elif this_end_time  < end_time and this_end_time > start_time:
            selected_measurements.append(measure)
    
    return selected_measurements

def calc_host_power(measure, idle_watt, util_watt, start_time_utc = 0, end_time_utc = 0):
    this_end_time = time.mktime(parser.parse(measure[0]).replace(tzinfo=None).timetuple())
    duration = int(measure[1])
    this_start_time = this_end_time - duration
    
    if start_time_utc > this_start_time and start_time_utc < this_end_time:
        this_start_time = start_time_utc
    
    if end_time_utc > this_start_time and end_time_utc < this_end_time:
        this_end_time = end_time_utc
    
    util = float(measure[2])/100 # XX percent to 0.XX
    
    if util < POWEROFF_CPU_UTIL:
        print "Debug: utiil is less than threshold. ", util
        return 0
    
    power = float(idle_watt) + float(util_watt) * util;
    dur = float(this_end_time - this_start_time)/3600 # convert to hour.
    return power * dur

def get_host_power(host, start_time, end_time = 0):
    conn_gnocchi = cloud_monitor.connect_gnocchi()
    all_measurements = cloud_monitor.host_utilization_all(conn_gnocchi, hostname=host)
    
    if end_time == 0:
        end_time = get_current_time() # current time
    
    measurements = select_measurements_since(all_measurements, start_time, end_time)
    idle_watt, working_watt = POWER_SPEC[host]
    watthour = 0
    
    for m in measurements:
        watthour += calc_host_power(m, idle_watt, working_watt, start_time, end_time)
    
    return watthour

def generate_hosts_power_data(hostlist, start_time, end_time = 0):
    host_power = {}
    for host in hostlist:
        host_power[host] = get_host_power(host, start_time, end_time)
    return host_power

def get_all_host_power(start_time = 0, end_time = 0):
    hostlist = POWER_SPEC.keys()
    host_power = generate_hosts_power_data(hostlist, start_time, end_time)
    #print "Debug(host): ", host_power
    
    total_power = 0.0
    for p in host_power.values():
        total_power += p
    
    return total_power

### Switches ####
def parse_switch_port_statistics(data):
    port_stat = {}
    for node in data:
        node_id = node['id'].split(":")[-1]
        port_stat[node_id] = {}
        for connector in node['node-connector']:
            port_id = connector['id'].split(":")[-1]
            if port_id == "LOCAL":
                continue
            port_send = connector["opendaylight-port-statistics:flow-capable-node-connector-statistics"]["bytes"]["transmitted"]
            port_recv = connector["opendaylight-port-statistics:flow-capable-node-connector-statistics"]["bytes"]["received"]
            port_bytes = port_send+port_recv
            port_stat[node_id][port_id] = port_bytes
    return port_stat

def calc_switch_power(switch, active_port, dur):
    if "all" in SWITCH_SPEC:
        idle_watt, port_watt = SWITCH_SPEC["all"]
    else:
        idle_watt, port_watt = SWITCH_SPEC[switch]
    
    power = float(idle_watt) + float(port_watt)*active_port
    dur = float(dur)/3600 # convert to hour
    return power * dur

def get_active_ports(prev_stat, curr_stat):
    active_ports = {}
    for switch in prev_stat:
        active_ports[switch] = 0
        for port in prev_stat[switch]:
            prev_byte = prev_stat[switch][port]
            curr_byte = curr_stat[switch][port]
            if curr_byte > THRESHOLD_ACTIVE_SWITCH:
                active_ports[switch] += 1
    return active_ports


def generate_switches_power_data(prev_stat, curr_stat, dur):
    switch_power = {}
    active_ports = get_active_ports(prev_stat, curr_stat)
    for switch in active_ports:
        power = calc_switch_power(switch, active_ports[switch], dur)
        switch_power[switch] = power
    return switch_power

prev_port_stat = {}
accum_switch_power = 0.0
def get_all_switch_power_accum(duration=300):
    global prev_port_stat, accum_switch_power
    
    data = network_manager.get_all_switch_info()
    curr_port_stat = parse_switch_port_statistics(data)
    switch_power = generate_switches_power_data(prev_port_stat, curr_port_stat, duration)
    prev_port_stat = curr_port_stat
    
    #print "Debug(switch): ", switch_power
    total_power = 0.0
    for p in switch_power.values():
        total_power += p
    
    accum_switch_power += total_power
    return accum_switch_power

host_prev, switch_prev=0,0

def print_power_consumption(interval=60, fin_duration=0):
    global host_prev, switch_prev
    start_time = get_current_time()
    
    print "Initializing..."
    get_all_switch_power_accum(0)
    
    print "Power monitoring started... now=%d, update every %d seconds"%(start_time, interval)
    time_processing = get_current_time() - start_time
    while True:
        r_interval = interval - time_processing
        r_interval = max(0, r_interval)
        time.sleep(r_interval)
        processing_begin =  get_current_time()
        duration = processing_begin - start_time
        
        host_power = get_all_host_power(start_time)
        switch_power = get_all_switch_power_accum(interval)
        print "%s(%d): All=%.1f, Host=%.1f, Switch=%.1f / Delta: A=%.1f, H=%.1f, S=%.1f)"%(time.strftime('%H:%M:%S', time.gmtime(duration)), processing_begin, \
            host_power+switch_power, host_power, switch_power, host_power+switch_power-host_prev-switch_prev, host_power-host_prev, switch_power-switch_prev)
        host_prev, switch_prev = host_power, switch_power
        if fin_duration and duration > fin_duration+60:
            print "Power monitoring done at %d"%(get_current_time())
            return
        
        time_processing = get_current_time() - processing_begin


def estimate_power_consumption(start_time, duration):
    print "Estimating power consumption..."
    if start_time <= 0:
        start_time += get_current_time()
    if duration <= 0:
        duration = get_current_time() - start_time
    
    end_time=start_time + duration
    get_all_switch_power_accum(0)
    time.sleep(3)
    
    host_power = get_all_host_power(start_time, end_time)
    switch_power = get_all_switch_power_accum(duration)
    print "%s: All=%.1f (Host=%.1f, Switch=%.1f)"%(time.strftime('%H:%M:%S', time.gmtime(duration)), host_power+switch_power, host_power, switch_power)


# Main
def _print_usage():
    print("Usage:\t python %s start <interval> [duration]\t - Start power monitoring with interval time, for the set duration"%(sys.argv[0]))
    print("Usage:\t python %s estimate <start_utc_sec> <duration_sec> \t - Show the estimated power consumption. Negative seconds means relative time from now. (-600 means 10 minuts before now)"%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
    if sys.argv[1] == "start":
        dur = 0
        if len(sys.argv) > 3 :
            dur = int(sys.argv[3])
        print_power_consumption(int(sys.argv[2]), dur)
    elif sys.argv[1] == "estimate":
        estimate_power_consumption(int(sys.argv[2]), int(sys.argv[3]))
    else:
        _print_usage()
        return

if __name__ == '__main__':
    main()