#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
#!/usr/bin/env python
import requests
import json
import sys
from collections import defaultdict
import sdcon_config
# sFlow-rt API: http://www.sflow-rt.com/reference.php

def set_sflow_flow (collector_url, name , keys, value):
    keylist = ""
    for key in keys:
        keylist+=key+','
    keylist = keylist[:-1]
    flow = {'keys':keylist,'value':value,'log':True}
    url = collector_url+'/flow/'+name+'/json'
    try:
        response = requests.put(url,data=json.dumps(flow))
        response.raise_for_status();
    except(requests.exceptions.Timeout,requests.exceptions.RequestException,requests.exceptions.RequestException) as err:
        print(err)

def del_sflow_flow(collector_url, name):
    try:
        url = collector_url+'/flow/'+name+'/json'
        response = requests.delete(url)
        response.raise_for_status();
    except(requests.exceptions.Timeout,requests.exceptions.RequestException,requests.exceptions.RequestException) as err:
        print(err)

def get_sflow_flow(collector_url, name, switch_ip="ALL"):
    try:
        url = collector_url+'/activeflows/'+switch_ip+'/'+name+'/json?maxFlows=200'
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except(requests.exceptions.Timeout,requests.exceptions.RequestException,requests.exceptions.RequestException) as err:
        print(err)

def get_sflow_dump(collector_url, name, switch_ip="ALL"):
    try:
        #SFLOW_COLLECTOR_URL/dump/192.168.99.100/ip_flows/json
        url = collector_url+'/dump/'+switch_ip+'/'+name+'/json'
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except(requests.exceptions.Timeout,requests.exceptions.RequestException,requests.exceptions.RequestException) as err:
        print(err)

def get_sflow_flowlocations(collector_url, name, key):
    try:
        url = collector_url+'/flowlocations/ALL/'+name+'/json?key='+key
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except(requests.exceptions.Timeout,requests.exceptions.RequestException,requests.exceptions.RequestException) as err:
        print(err)

# Main
def main():
    #del_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, 'vms')
    set_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, 'vms', ['ipsource','ipdestination'], 'bytes')
    set_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, 'migrations', ['ipsource','ipdestination','tcpdestinationport'], 'bytes')
    json_object = get_sflow_flow(sdcon_config.SFLOW_COLLECTOR_URL, 'vms')
    print(json_object)
    
    vm2vm = defaultdict(dict)
    vm2host = {}
    for objects in json_object:
        for key in objects:
            #print( objects['key'])
            # This part records traffic between source ips to destination ips in vm2vm dictionary 
            ips = objects['key']
            ipsrc = ips.split(',')[0]
            ipdes = ips.split(',')[1]
            print("%s %s" %(ipsrc,ipdes))
            vm2vm[ipsrc][ipdes] = objects['value']
            #this part records vm to host association
            #first we change the ip to our range 192.168.99.2 -> 192.168.0.2
            ip99parts = objects['agent'].split('.')
            hostip = ip99parts[0]+'.'+ip99parts[1]+'.0.'+ip99parts[3]
            vm2host[ipsrc]= hostip
    
    for ipsrc in vm2vm:
        for ipdes in vm2vm[ipsrc]:
            print "%s"%(vm2vm[ipsrc][ipdes]),
        print
    for k,v in vm2host.items():
        print('%s ---> %s'%(k,v))

if __name__ == '__main__':
    main()