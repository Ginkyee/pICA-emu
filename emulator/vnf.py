# -*- coding: utf-8 -*-

# @Author: Shenyunbin
# @email : yunbin.shen@mailbox.tu-dresden.de / shenyunbin@outlook.com
# @create: 2021-05-05 20:41:14
# @modify: 2021-05-16 15:41:14
# @desc. : [description]


"""
Forwarding VNF via packet socket.
"""

from server import EVAL_TIMES
import numpy as np
import pickle
import time
from picautils.icanetwork import icanetwork
from picautils.icabuffer import ICABuffer
from picautils.packetutils import *
from simpleemu.simplecoin import SimpleCOIN
from simpleemu.simpleudp import simpleudp
from measurement.measure import measure_write

EVAL_TIMES = []
process_time = 0

IFCE_NAME, NODE_IP = simpleudp.get_local_ifce_ip('10.0.')
DEF_INIT_SETTINGS = {'is_finish': False, 'm': np.inf, 'W': None, 'proc_len': np.inf,
                     'proc_len_multiplier': 2, 'node_max_ext_nums': [np.inf], 'node_max_lens': [np.inf]}
init_settings = {}
init_settings.update(DEF_INIT_SETTINGS)
dst_ip_addr = None
ica_processed = False

ica_buf = ICABuffer(max_size=(4, 160000))

app = SimpleCOIN(ifce_name=IFCE_NAME, n_func_process=1)


# main function for processing the data
# af_packet is the raw af_packet from the socket
@app.main()
def main(simplecoin, af_packet):
    # parse the raw packet to get the ip/udp infomations like ip, port, protocol, data
    packet = simpleudp.parse_af_packet(af_packet)
    # if prorocol is 17, that means is udp
    if packet['Protocol'] == 17 and packet['IP_src'] != NODE_IP:
        # the 1st byte is header other bytes are datas (here is "chunk")
        chunk = packet['Chunk']
        header = int(chunk[0])
        if header == HEADER_CLEAR_CACHE:
            print('*** vnf clearing cache!')
            simplecoin.submit_func(pid=0, id='clear_cache')
            print('*** vnf transmiting clearing message to next node!')
            simplecoin.forward(af_packet)
        elif header == HEADER_INIT:
            init_settings.update(pickle.loads(chunk[1:]))
            if init_settings['is_finish'] == False:
                print('*** vnf initializing!')
                simplecoin.submit_func(pid=0, id='set_init_settings', args=(
                    init_settings, (packet['IP_dst'], packet['Port_dst']),))
            else:
                print('*** vnf transmit init_settings!')
                simplecoin.forward(af_packet)
                measure_write(IFCE_NAME, ['transmit', time.time()])
        elif header == HEADER_DATA or header == HEADER_FINISH:
            simplecoin.submit_func(
                pid=0, id='put_ica_buf', args=(pickle.loads(chunk[1:]),))
            simplecoin.forward(af_packet)
            if header == HEADER_FINISH:
                t = time.localtime()
                print('*** last_pkt:', time.strftime("%H:%M:%S", t))
        else:
            pass


@app.func('clear_cache')
def clear_cache(simplecoin):
    global DEF_INIT_SETTINGS, init_settings, dst_ip_addr, ica_processed, EVAL_TIMES
    EVAL_TIMES = []
    ica_processed = False
    ica_buf.init()
    init_settings.update(DEF_INIT_SETTINGS)


@app.func('set_init_settings')
def set_init_settings(simplecoin, _init_settings, _dst_ip_addr):
    global DEF_INIT_SETTINGS, init_settings, dst_ip_addr, ica_processed, process_time
    process_time = 0
    init_settings.update(_init_settings)
    dst_ip_addr = _dst_ip_addr
    if ica_buf.size() >= init_settings['proc_len']:
        print('call pica')
        simplecoin.submit_func(pid=-1, id='pica_service')


@app.func('put_ica_buf')
def ica_buf_put(simplecoin, data):
    global DEF_INIT_SETTINGS, init_settings, dst_ip_addr, ica_processed
    if ica_processed == False:
        ica_buf.put(data)
        if ica_buf.size() >= init_settings['proc_len']:
            simplecoin.submit_func(pid=-1, id='pica_service')

# the function app.func('xxx') will create a new thread to run the function


@app.func('pica_service')
def pica_service(simplecoin):
    global DEF_INIT_SETTINGS, init_settings, dst_ip_addr, ica_processed, EVAL_TIMES, process_time
    if not ica_processed:
        while True:
            if init_settings['is_finish'] == True or init_settings['node_max_ext_nums'][0] == 0 or init_settings['proc_len'] > init_settings['node_max_lens'][0]:
                del init_settings['node_max_lens'][0]
                del init_settings['node_max_ext_nums'][0]
                simplecoin.sendto(pktutils.serialize_data(
                    HEADER_INIT, init_settings), dst_ip_addr)
                measure_write(IFCE_NAME, EVAL_TIMES)
                ica_processed = True
                ica_buf.init()
                init_settings.update(DEF_INIT_SETTINGS)
                print('*** vnf pica processing finished!')
                break
            elif ica_buf.size() >= init_settings['proc_len']:
                if init_settings['proc_len'] == init_settings['m']:
                    print('*** vnf pica processing!')
                    time_start = time.time()
                    # EVAL_TIMES += ['fica_start', time_start]
                    icanetwork.fastica_nw(init_settings, ica_buf)
                    time_finish = time.time()
                    # EVAL_TIMES += ['fica_end',time_finish]
                    init_settings['is_finish'] = True
                else:
                    print('*** vnf pica processing!')
                    time_start = time.time()
                    # EVAL_TIMES += ['fica_start', time_start]
                    icanetwork.pica_nw(init_settings, ica_buf)
                    time_finish = time.time()
                    # EVAL_TIMES += ['fica_end',time_finish]
                    init_settings['node_max_ext_nums'][0] -= 1
                    if init_settings['proc_len'] > init_settings['m']:
                        init_settings['proc_len'] = init_settings['m']
                process_time = time_finish - time_start
            else:
                break
            EVAL_TIMES += [process_time]


if __name__ == "__main__":
    app.run()
