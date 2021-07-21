#!/usr/bin/env python3.7

import asyncio
import logging
from datetime import datetime

from pyintesishome import IntesisHome

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s.%(funcName)s +%(lineno)s: %(levelname)-8s [%(process)d] %(message)s",
)


async def main(loop):
    # def main():

    username = "xxxxxx"
    password = "yyyyyyy"
    idd = "zzzzzzzzzzz"
    aquarea = None

    aquarea = IntesisHome(username, password, loop=loop)
    await aquarea.connect()
    await aquarea.poll_status()

    today = datetime.today()
    tank_temp = aquarea._get_gen_num_value(idd, "tank_water_temperature")
    outdoor_temp = aquarea.get_outdoor_temperature(idd)
    tank_set_point = aquarea._get_gen_num_value(idd, "tank_setpoint_temperature")
    water_outlet_temp = aquarea._get_gen_num_value(idd, "water_outlet_temperature")
    water_inlet_temp = aquarea._get_gen_num_value(idd, "water_inlet_temperature")
    mode = aquarea.get_mode(idd)
    water_target_temp = aquarea._get_gen_num_value(idd, "water_target_temperature")
    wifi_signal = aquarea.get_rssi(idd)
    power = aquarea.get_power_state(idd)
    cool_setpoint = aquarea._get_gen_num_value(idd, "cool_water_setpoint_temperature")

    print(
        today.strftime("%Y-%m-%d %H:%M:%S: ")
        + f"Mode = {mode}, Tank temp = {tank_temp:.1f}°C, Tank set point = {tank_set_point:.1f}°C, WIFI signal = {wifi_signal}, Power = {power}"
    )
    if power == "on" and (mode == "heat" or mode == "heat+tank"):
        print(
            today.strftime("%Y-%m-%d %H:%M:%S: ")
            + f"Water Outlet temp = {water_outlet_temp:.1f}°C, Water Inlet temp = {water_inlet_temp:.1f}°C, Water Target temp = {water_target_temp:.1f}°C, Outdoor temp = {outdoor_temp:.1f}°C"
        )
    elif power == "on" and (mode == "cool" or mode == "cool+tank"):
        print(
            today.strftime("%Y-%m-%d %H:%M:%S: ")
            + f"Water Outlet temp = {water_outlet_temp:.1f}°C, Water Inlet temp = {water_inlet_temp:.1f}°C, Water Target temp = {cool_setpoint:.1f}°C, Outdoor temp = {outdoor_temp:.1f}°C"
        )


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main(loop))
