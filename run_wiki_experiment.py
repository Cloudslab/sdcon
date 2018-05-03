#
# Title:        SDCon
# Description:  Integrated Control Platform for Software-Defined Clouds
# Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
#
# Copyright (c) 2018, The University of Melbourne, Australia
#
import sys, cloud_manager

CL_MIDFIX = "-wikiclient-"
SV_MIDFIX = "-wikiserver-"
DB_POSTFIX = "-wikibench-db"

COMP_RATIO = {
    "jay1":2,
    "jay2":1
}

def _print_name_host_ip(conn_os, vm_name, vm_ip):
    host = cloud_manager.get_vm_hostname(conn_os, vm_name)
    print "# %s : %s : %s"%(vm_name, host, vm_ip)

def __cmd_db_change(sv, db_new):
    db_old = "192.168.0.201"
    
    ssh = "ssh %s "%(sv)
    print ssh + '''"sed -i 's/%s/%s/g' /var/lib/mediawiki/LocalSettings.php" & \\''' %(db_old, db_new)

def __cmd_db_check(sv):
    ssh = "echo %s;ssh %s "%(sv,sv)
    print ssh + "'cat /var/lib/mediawiki/LocalSettings.php | grep DBserver' ;\\"

def __cmd_echo_hi(cl,sv):
    print "echo %s;ssh %s 'echo hi' ;\\"%(cl, cl)
    print "echo %s;ssh %s 'echo hi' ;\\"%(sv, sv)
    
def __cmd_setup_git(cl, sv):
    ssh = "ssh %s "%(cl)
    print "scp ~/.netrc %s:./ ; \\"%(cl)
    print ssh + "'chmod 600 ~/.netrc' ;\\"

def __cmd_git_pull(cl, sv):
    ssh = "ssh %s "%(cl)
    print ssh + "'cd ~/clouds-pi && git pull'& \\"

def __cmd_restart_apache(sv):
    ssh = "ssh %s "%(sv)
    print ssh + "'sudo systemctl restart apache2' &\\"

def __cmd_check_result_remote(cl):
    ssh = "echo %s;ssh %s "%(cl,cl)
    print ssh + "'python ~/clouds-pi/wiki-exp/result_aggr.py < ~/trace900.txt.log' ;\\"

def __cmd_check_result_local(cl):
    print "python ~/clouds-pi/wiki-exp/result_aggr.py < ./result-%s.log  ; \\"%(cl)

def _group_check_result_aggr(cl_group):
    for prefix in cl_group:
        cmd = "echo 'Result ======================================== %s'; cat "%(prefix)
        for ip in cl_group[prefix]:
            cmd += "./result-%s.log "%(ip)
            
        cmd += "| python ~/clouds-pi/wiki-exp/result_aggr.py ;\\"
        print cmd

def __cmd_start_exp(cl, sv, comp, time):
    ssh = "ssh %s "%(cl)
    print ssh + "'cd ~/clouds-pi/wiki-exp/ && ./start_both.sh ~/trace900.txt %s %d %d' & \\"%(sv, comp, time)

def __cmd_test_http(cl, sv):
    ssh = "ssh %s "%(cl)
    print ssh + '''"curl http://%s/wiki/JungminSon" | grep ">JungminSon</h1>" &'''%(sv)

def __cmd_copy_result_dir(cl, result_dir):
    print "scp %s:~/trace900.txt.log %s/result-%s.log ; \\"%(cl, result_dir, cl)

def _group_start_exp(pairs, pairs_comp, exp_time, exp_name = "current"):
    print "\n\n echo 'Time to start.. %d sec'; \\"%(exp_time)
    result_dir = "~/result-wiki/%s/%d"%(exp_name, exp_time)
    print "mkdir -p "+result_dir
    
    print "python -u power_monitor.py start 60 %d >> %s/power.txt & \\"%(exp_time+240, result_dir)
    print "echo 'sleeping 60 seconds..' ; sleep 60 ;\\"
    for cl_ip, sv_ip in pairs:
        __cmd_start_exp(cl_ip, sv_ip, pairs_comp[(cl_ip, sv_ip)], exp_time)
    print "echo 'waiting to finish....' ; sleep %d; python -u power_monitor.py estimate -%d 0 >> %s/power.txt"%(exp_time+240-60 +exp_time/10, exp_time+240, result_dir)
    
    print "\n echo 'copying results.....' ; \\"
    for cl_ip, sv_ip in pairs:
        __cmd_copy_result_dir(cl_ip, result_dir)
    print "echo '%d is done.. result is in %s' ; sleep 10"%(exp_time, result_dir)

def _group_restart_apache(servers):
    print "\n\n##========================================== Restart Apache ==========================================##"
    for sv_ip in servers:
        __cmd_restart_apache(sv_ip)

script_file = open('./exp.script', 'w')
def __redirect_stdout(is_file = True):
    if is_file:
        sys.stdout = script_file
    else:
        sys.stdout = sys.__stdout__

def print_exp_set(pairs, pairs_comp, exp_name = "current", is_auto=True):
    _group_start_exp(pairs, pairs_comp, 300, exp_name)
    _group_start_exp(pairs, pairs_comp, 1800, exp_name)

    if is_auto:
        __redirect_stdout(is_file = True)
        _group_start_exp(pairs, pairs_comp, 300, exp_name)
        _group_start_exp(pairs, pairs_comp, 1800, exp_name)
        __redirect_stdout(is_file = False)

def print_auto_script(s):
    print s
    __redirect_stdout(is_file = True)
    print s
    __redirect_stdout(is_file = False)
    
    
def wiki_gen_command(prefix_list, conn_os):
    pairs = []
    change_db_sv={}
    db_ips = {}
    servers = []
    clients = {}
    pairs_comp ={}
    
    for (prefix, num) in prefix_list:
        change_db_sv[prefix] = []
        clients[prefix] = []
        db_name = prefix + DB_POSTFIX
        db_ips[prefix]  = cloud_manager.get_vm_ip(conn_os, db_name)
        _print_name_host_ip(conn_os, db_name, db_ips[prefix] )
        
        for n in range(1, num+1):
            cl_name = prefix+CL_MIDFIX+str(n)
            sv_name = prefix+SV_MIDFIX+str(n)
            cl_ip = cloud_manager.get_vm_ip(conn_os, cl_name)
            sv_ip = cloud_manager.get_vm_ip(conn_os, sv_name)
            _print_name_host_ip(conn_os, cl_name, cl_ip)
            _print_name_host_ip(conn_os, sv_name, sv_ip)
            pairs.append( (cl_ip, sv_ip) )
            pairs_comp[(cl_ip, sv_ip)] = COMP_RATIO[prefix]
            servers.append( sv_ip )
            change_db_sv[prefix].append(sv_ip)
            clients[prefix].append(cl_ip)
            
    print "\n\n## Say hi >>"
    for cl_ip, sv_ip in pairs:
        __cmd_echo_hi(cl_ip, sv_ip)
    
    print "\n\n##========================================== Client settings ==========================================##"
    
    print "\n\n## Copy git authentication file....."
    for cl_ip, sv_ip in pairs:
        __cmd_setup_git(cl_ip, sv_ip)
    
    print "\n\n## Download Git....!!!!"
    for cl_ip, sv_ip in pairs:
        __cmd_git_pull(cl_ip, sv_ip)
    
    print "\n\n##========================================== Apache settings ==========================================##"
    print "\n\n## MediaWiki change DB settings >>"
    for (prefix, num) in prefix_list:
        dp_ip = db_ips[prefix]
        for sv_ip in change_db_sv[prefix]:
            __cmd_db_change(sv_ip, dp_ip)

    print "\n\n## Check DB settings >>"
    for sv_ip in servers:
        __cmd_db_check(sv_ip)

    
    print "\n\n##========================================== Test a little bit... ==========================================##"
    _group_start_exp(pairs, pairs_comp, 10)

    print "\n\n## How was the test??"
    for cl_ip, sv_ip in pairs:
        __cmd_check_result_remote(cl_ip)
    
    _group_restart_apache(servers)
    
    print "\n\n##========================== Let's start the experiment! ===============================##"
    print "\n\n##================== for no traffic ##"
    print_exp_set(pairs, pairs_comp, "notraffic")
    
    print "\n\n##================== with generated traffic ##"
    print_auto_script("\nsleep 60; echo 'start generating traffic'; (sh -s < gen_traffic.sh )& sleep 60;")
    print_exp_set(pairs, pairs_comp, "withtraffic")
    
    print "\n\n##================== with generated traffic and dynamic flow ##"
    print_auto_script("\nsleep 60; echo 'start dynamic flow'; (python resource_provisioner.py deploy-net df vmconf-wiki-1-large.json vmconf-wiki-2-small.json)& sleep 60;")
    print_exp_set(pairs, pairs_comp, "df")
    print_auto_script("\nsleep 60; echo 'Stop generating traffic AND dynamic flow. use fg command!'")
    
    print "\n\n##================== STOP Generate flow!! ##"
    print_exp_set(pairs, pairs_comp, "bw", is_auto=False)
    
    print "\n\n##========================================== Check the result ==========================================##"
    for cl_ip, sv_ip in pairs:
        __cmd_check_result_local(cl_ip)
    _group_check_result_aggr(clients)
# Main
def _print_usage():
    print("Usage:\t python %s <prefix> <num_vm> [ <prefix> <num_vm> ] ...  : generate a script to run wikibench)"%(sys.argv[0]))
    print("Example:\t python %s 4 jay1 jay2"%(sys.argv[0]))

# Main
def main():
    if len(sys.argv) < 2:
        _print_usage()
        return
    conn_os = cloud_manager.connect_openstack(sdcon_config.OPENSTACK_AUTH_URL, sdcon_config.OPENSTACK_AUTH_ADMIN_ID, sdcon_config.OPENSTACK_AUTH_ADMIN_PW)

    p_list=[]
    for n in range(1, len(sys.argv), 2):
        p_list.append( (sys.argv[n], int(sys.argv[n+1]) ) )
    wiki_gen_command(p_list, conn_os)

if __name__ == '__main__':
    main()

