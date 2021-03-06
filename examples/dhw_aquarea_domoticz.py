#!/usr/bin/env python3.7

import requests
from optparse import OptionParser
from pyintesishome import IntesisHome
import sys
import pycurl
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import time
from datetime import datetime
import asyncio
import logging
try:
    from io import BytesIO
except ImportError:
    from StringIO import StringIO as BytesIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s.%(funcName)s +%(lineno)s: %(levelname)-8s [%(process)d] %(message)s',)

def aquarea_to_domoticz(broker,
            port,
            temp_idx,
            tank_set_point_idx,
            water_set_point_idx,
            ext_temp_idx,
            out_temp_idx,
            in_temp_idx,
            power_idx,
            date,
            power,
            mode,
            tank_temp,
            tank_set_point,
            water_target_temp,
            outdoor_temp,
            water_outlet_temp,
            water_inlet_temp,
            cool_setpoint
            ):
        msgs = ''
        if (mode == 'tank' or power  == 'off'):
            msgs = [{'topic':"domoticz/in", 'payload':"{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (temp_idx, str(tank_temp))},
                    ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (tank_set_point_idx, str(tank_set_point)), 0, False),
                    ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (ext_temp_idx, str(outdoor_temp)), 0, False),
                    ("domoticz/in", "{\"idx\":%d,\"nvalue\":%d}" % (power_idx, 1 if power == 'on' else 0), 0, False)
                   ]
        elif (power == 'on' and (mode == 'heat' or mode == 'heat+tank'  or mode == 'cool+tank' or mode == 'cool')):
            if (mode == 'heat' or mode == 'heat+tank'):
                msgs = [{'topic':"domoticz/in", 'payload':"{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (temp_idx, str(tank_temp))},
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (tank_set_point_idx, str(tank_set_point)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (water_set_point_idx, str(water_target_temp)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (ext_temp_idx, str(outdoor_temp)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (out_temp_idx, str(water_outlet_temp)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":%d}" % (power_idx, 1 if power == 'on' else 0), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (in_temp_idx, str(water_inlet_temp)), 0, False)
                       ]
            else:
                msgs = [{'topic':"domoticz/in", 'payload':"{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (temp_idx, str(tank_temp))},
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (tank_set_point_idx, str(tank_set_point)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (water_set_point_idx, str(cool_setpoint)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (ext_temp_idx, str(outdoor_temp)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (out_temp_idx, str(water_outlet_temp)), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":%d}" % (power_idx, 1 if power == 'on' else 0), 0, False),
                        ("domoticz/in", "{\"idx\":%d,\"nvalue\":0,\"svalue\":\"%s\"}" % (in_temp_idx, str(water_inlet_temp)), 0, False)
                       ]
                       
        print(msgs)
         
        print(broker)
        rc = publish.multiple(msgs, hostname=broker, port=port, client_id="pyIntesisHome2")
        print(date.strftime("%Y-%m-%d %H:%M:%S: ") + "Publish: %s" % (rc))


async def main(loop):

    username="xxxxxx"
    password="yyyyyyyyy"
    idd = zzzzzzzz
    aquarea = None
    msgs = None

    aquarea = IntesisHome(username, password, loop=loop)
    await aquarea.connect()
    await aquarea.poll_status()

    today = datetime.today()
    tank_temp = aquarea._get_gen_num_value(idd, "tank_water_temperature")
    outdoor_temp = aquarea.get_outdoor_temperature(idd)
    tank_set_point = aquarea._get_gen_num_value(idd,"tank_setpoint_temperature")
    water_outlet_temp = aquarea._get_gen_num_value(idd,"water_outlet_temperature")
    water_inlet_temp = aquarea._get_gen_num_value(idd,"water_inlet_temperature")
    mode = aquarea.get_mode(idd)
    water_target_temp = aquarea._get_gen_num_value(idd,"water_target_temperature")
    wifi_signal = aquarea.get_rssi(idd)
    power = aquarea.get_power_state(idd)
    cool_setpoint = aquarea._get_gen_num_value(idd,"cool_water_setpoint_temperature")

    print(today.strftime("%Y-%m-%d %H:%M:%S: ") + f"Mode = {mode}, Tank temp = {tank_temp:.1f}°C, Tank set point = {tank_set_point:.1f}°C, WIFI signal = {wifi_signal}, Power = {power}")
    if (power == 'on' and (mode == 'heat' or mode == 'heat+tank')):
        print(today.strftime("%Y-%m-%d %H:%M:%S: ") + f"Water Outlet temp = {water_outlet_temp:.1f}°C, Water Inlet temp = {water_inlet_temp:.1f}°C, Water Target temp = {water_target_temp:.1f}°C, Outdoor temp = {outdoor_temp:.1f}°C")
    elif (power == 'on' and (mode == 'cool' or mode == 'cool+tank')):
        print(today.strftime("%Y-%m-%d %H:%M:%S: ") + f"Water Outlet temp = {water_outlet_temp:.1f}°C, Water Inlet temp = {water_inlet_temp:.1f}°C, Water Target temp = {cool_setpoint:.1f}°C, Outdoor temp = {outdoor_temp:.1f}°C")

    if (wifi_signal > 0):
        temp_idx = 8
        tank_set_point_idx = 9
        water_set_point_idx = 13
        ext_temp_idx = 12
        out_temp_idx = 10
        in_temp_idx = 11
        power_idx = 14

        broker = "192.168.2.32"
        port = 1883

        aquarea_to_domoticz(broker,
                            port,
                            temp_idx,
                            tank_set_point_idx,
                            water_set_point_idx,
                            ext_temp_idx,
                            out_temp_idx,
                            in_temp_idx,
                            power_idx,
                            today,
                            power,
                            mode,
                            tank_temp,
                            tank_set_point,
                            water_target_temp,
                            outdoor_temp,
                            water_outlet_temp,
                            water_inlet_temp,
                            cool_setpoint)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main(loop))
    #main()

