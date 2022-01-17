""" Constants for pyintesishome """
INTESIS_CMD_STATUS = '{"status":{"hash":"x"},"config":{"hash":"x"}}'
INTESIS_NULL = 32768

DEVICE_INTESISHOME = "IntesisHome"
DEVICE_AIRCONWITHME = "airconwithme"
DEVICE_ANYWAIR = "anywair"
DEVICE_INTESISHOME_LOCAL = "intesishome_local"
DEVICE_INTESISBOX = "IntesisBox"

API_DISCONNECTED = "Disconnected"
API_CONNECTING = "Connecting"
API_AUTHENTICATED = "Connected"
API_AUTH_FAILED = "Wrong username/password"

CONFIG_MODE_BITS = {1: "auto", 2: "heat", 4: "dry", 8: "fan", 16: "cool"}
OPERATING_MODE_BITS = {
    1: "heat",
    2: "heat+tank",
    4: "tank",
    8: "cool+tank",
    16: "cool",
    32: "auto",
    64: "auto+tank",
}

INTESIS_MAP = {
    1: {"name": "power", "values": {0: "off", 1: "on"}},
    2: {
        "name": "mode",
        "values": {0: "auto", 1: "heat", 2: "dry", 3: "fan", 4: "cool"},
    },
    4: {
        "name": "fan_speed",
    },
    5: {
        "name": "vvane",
        "values": {
            0: "auto/stop",
            1: "manual1",
            2: "manual2",
            3: "manual3",
            4: "manual4",
            5: "manual5",
            6: "manual6",
            7: "manual7",
            8: "manual8",
            9: "manual9",
            10: "swing",
        },
    },
    6: {
        "name": "hvane",
        "values": {
            0: "auto/stop",
            10: "swing",
            1: "manual1",
            2: "manual2",
            3: "manual3",
            4: "manual4",
            5: "manual5",
        },
    },
    9: {"name": "setpoint"},
    10: {"name": "temperature"},
    12: {"name": "remote_controller_lock"},
    13: {"name": "working_hours"},
    14: {"name": "alarm_status"},
    15: {"name": "error_code"},
    34: {"name": "quiet_mode", "values": {0: "off", 1: "on"}},
    35: {"name": "setpoint_min"},
    36: {"name": "setpoint_max"},
    37: {"name": "outdoor_temp"},
    38: {"name": "water_outlet_temperature"},
    39: {"name": "water_inlet_temperature"},
    42: {
        "name": "climate_working_mode",
        "values": {0: "comfort", 1: "eco", 2: "powerful"},
    },
    44: {
        "name": "tank_working_mode",
        "values": {0: "comfort", 1: "eco", 2: "powerful"},
    },
    45: {"name": "tank_water_temperature"},
    46: {"name": "solar_status"},
    48: {"name": "thermoshift_heat_eco"},
    49: {"name": "thermoshift_cool_eco"},
    50: {"name": "thermoshift_heat_powerful"},
    51: {"name": "thermoshift_cool_powerful"},
    52: {"name": "thermoshift_tank_eco"},
    53: {"name": "thermoshift_tank_powerful"},
    54: {"name": "error_reset"},
    55: {"name": "heat_thermo_shift"},
    56: {"name": "cool_water_setpoint_temperature"},
    57: {"name": "tank_setpoint_temperature"},
    58: {
        "name": "operating_mode",
        "values": {
            0: "maintenance",
            1: "heat",
            2: "heat+tank",
            3: "tank",
            4: "cool+tank",
            5: "cool",
            6: "auto",
            7: "auto+tank",
        },
    },
    60: {"name": "heat_8_10"},
    61: {"name": "config_mode_map"},
    62: {"name": "runtime_mode_restrictions"},
    63: {"name": "config_horizontal_vanes"},
    64: {"name": "config_vertical_vanes"},
    65: {"name": "config_quiet"},
    66: {"name": "config_confirm_off"},
    67: {
        "name": "config_fan_map",
        "values": {
            6: {1: "low", 2: "high"},
            7: {0: "auto", 1: "low", 2: "high"},
            14: {1: "low", 2: "medium", 3: "high"},
            15: {0: "auto", 1: "low", 2: "medium", 3: "high"},
            30: {1: "quiet", 2: "low", 3: "medium", 4: "high"},
            31: {0: "auto", 1: "quiet", 2: "low", 3: "medium", 4: "high"},
            62: {1: "quiet", 2: "low", 3: "medium", 4: "high", 5: "max"},
            63: {0: "auto", 1: "quiet", 2: "low", 3: "medium", 4: "high", 5: "max"},
            126: {
                1: "speed 1",
                2: "speed 2",
                3: "speed 3",
                4: "speed 4",
                5: "speed 5",
                6: "speed 6",
            },
            127: {
                0: "auto",
                1: "speed 1",
                2: "speed 2",
                3: "speed 3",
                4: "speed 4",
                5: "speed 5",
                6: "speed 6",
            },
        },
    },
    68: {"name": "instant_power_consumption"},
    69: {"name": "accumulated_power_consumption"},
    75: {"name": "config_operating_mode"},
    77: {"name": "config_vanes_pulse"},
    80: {"name": "aquarea_tank_consumption"},
    81: {"name": "aquarea_cool_consumption"},
    82: {"name": "aquarea_heat_consumption"},
    83: {"name": "heat_high_water_set_temperature"},
    84: {"name": "heating_off_temperature"},
    87: {"name": "heater_setpoint_temperature"},
    90: {"name": "water_target_temperature"},
    95: {
        "name": "heat_interval",
        "values": {
            1: 30,
            2: 60,
            3: 90,
            4: 120,
            5: 150,
            6: 180,
            7: 210,
            8: 240,
            9: 270,
            10: 300,
            11: 330,
            12: 360,
            13: 390,
            14: 420,
            15: 450,
            16: 480,
            17: 510,
            18: 540,
            19: 570,
            20: 600,
        },
    },
    107: {"name": "aquarea_working_hours"},
    123: {"name": "ext_thermo_control", "values": {85: "off", 170: "on"}},
    124: {"name": "tank_present", "values": {85: "off", 170: "on"}},
    125: {"name": "solar_priority", "values": {85: "off", 170: "on"}},
    134: {"name": "heat_low_outdoor_set_temperature"},
    135: {"name": "heat_high_outdoor_set_temperature"},
    136: {"name": "heat_low_water_set_temperature"},
    137: {"name": "farenheit_type"},
    140: {"name": "extremes_protection_status"},
    144: {"name": "error_code"},
    148: {"name": "extremes_protection"},
    149: {"name": "binary_input"},
    153: {"name": "config_binary_input"},
    168: {"name": "uid_binary_input_on_off"},
    169: {"name": "uid_binary_input_occupancy"},
    170: {"name": "uid_binary_input_window"},
    181: {"name": "mainenance_w_reset"},
    182: {"name": "mainenance_wo_reset"},
    183: {"name": "filter_clean"},
    184: {"name": "filter_due_hours"},
    185: {"name": "uid_185"},
    186: {"name": "uid_186"},
    191: {"name": "uid_binary_input_sleep_mode"},
    192: {"name": "error_address"},
    50000: {
        "name": "external_led",
        "values": {0: "off", 1: "on", 2: "blinking only on change"},
    },
    50001: {"name": "internal_led", "values": {0: "off", 1: "on"}},
    50002: {"name": "internal_temperature_offset"},
    50003: {"name": "temp_limitation", "values": {0: "off", 2: "on"}},
    50004: {"name": "cool_temperature_min"},
    50005: {"name": "cool_temperature_max"},
    50006: {"name": "heat_temperature_min"},
    50007: {"name": "heat_temperature_min"},
    60002: {"name": "rssi"},
}

COMMAND_MAP = {
    "power": {"uid": 1, "values": {"off": 0, "on": 1}},
    "mode": {"uid": 2, "values": {"auto": 0, "heat": 1, "dry": 2, "fan": 3, "cool": 4}},
    "operating_mode": {
        "uid": 58,
        "values": {
            "heat": 1,
            "heat+tank": 2,
            "tank": 3,
            "cool+tank": 4,
            "cool": 5,
            "auto": 6,
            "auto+tank": 7,
        },
    },
    "climate_working_mode": {
        "uid": 42,
        "values": {"comfort": 0, "eco": 1, "powerful": 2},
    },
    "fan_speed": {"uid": 4},
    "vvane": {
        "uid": 5,
        "values": {
            "auto/stop": 0,
            "swing": 10,
            "manual1": 1,
            "manual2": 2,
            "manual3": 3,
            "manual4": 4,
            "manual5": 5,
        },
    },
    "hvane": {
        "uid": 6,
        "values": {
            "auto/stop": 0,
            "swing": 10,
            "manual1": 1,
            "manual2": 2,
            "manual3": 3,
            "manual4": 4,
            "manual5": 5,
        },
    },
    "setpoint": {"uid": 9}
    # aquarea
    ,
    "quiet": {"uid": 34, "values": {"off": 0, "on": 1}},
    "tank": {"uid": 44, "values": {"comfort": 0, "eco": 1, "powerful": 2}},
    "reset_eror": {"uid": 54, "values": {"on": 1}},
    "tank_setpoint_temperature": {"uid": 57},
    "thermoshift_heat_eco": {"uid": 48, "min": 0, "max": 5},
    "thermoshift_cool_eco": {"uid": 49, "min": 0, "max": 5},  # 172
    "thermoshift_heat_powerful": {"uid": 50, "min": 0, "max": 5},
    "thermoshift_cool_powerful": {"uid": 51, "min": 0, "max": 5},  # 171
    "thermoshift_tank_eco": {"uid": 52, "min": 0, "max": 10},
    "thermoshift_tank_powerful": {"uid": 53, "min": 0, "max": 10},
    "heat_thermo_shift": {"uid": 55, "min": -5, "max": 5},
    "cool_water_setpoint_temperature": {"uid": 56},
    "heat_high_water_set_temperature": {"uid": 83, "min": 25, "max": 55},
    "heat_low_outdoor_set_temperature": {"uid": 134, "min": -15, "max": 15},
    "heat_high_outdoor_set_temperature": {"uid": 135, "min": -15, "max": 15},
    "heat_low_water_set_temperature": {"uid": 136, "min": 25, "max": 55},
    "resync": {"uid": 143, "values": {"on": 1}},
    "remote_control_block": {"uid": 12, "values": {"on": 2, "off": 0}},
}

# aquarea
ERROR_MAP = {
    0: {"code": "H00", "desc": "No abnormality detected"},
    2: {"code": "H91", "desc": "Tank booster heater OLP abnormality"},
    13: {"code": "F38", "desc": "Unknown"},
    20: {"code": "H90", "desc": "Indoor / outdoor abnormal communication"},
    36: {"code": "H99", "desc": "Indoor heat exchanger freeze prevention"},
    38: {"code": "H72", "desc": "Tank temperature sensor abnormality"},
    42: {"code": "H12", "desc": "Indoor / outdoor capacity unmatched"},
    156: {"code": "H76", "desc": "Indoor - control panel communication abnormality"},
    193: {"code": "F12", "desc": "Pressure switch activate"},
    195: {"code": "F14", "desc": "Outdoor compressor abnormal rotation"},
    196: {"code": "F15", "desc": "Outdoor fan motor lock abnormality"},
    197: {"code": "F16", "desc": "Total running current protection"},
    200: {"code": "F20", "desc": "Outdoor compressor overheating protection"},
    202: {"code": "F22", "desc": "IPM overheating protection"},
    203: {"code": "F23", "desc": "Outdoor DC peak detection"},
    204: {"code": "F24", "desc": "Refrigerant cycle abnormality"},
    205: {"code": "F27", "desc": "Pressure switch abnormality"},
    207: {"code": "F46", "desc": "Outdoor current transformer open circuit"},
    208: {"code": "F36", "desc": "Outdoor air temperature sensor abnormality"},
    209: {"code": "F37", "desc": "Indoor water inlet temperature sensor abnormality"},
    210: {"code": "F45", "desc": "Indoor water outlet temperature sensor abnormality"},
    212: {
        "code": "F40",
        "desc": "Outdoor discharge pipe temperature sensor abnormality",
    },
    214: {"code": "F41", "desc": "PFC control"},
    215: {
        "code": "F42",
        "desc": "Outdoor heat exchanger temperature sensor abnormality",
    },
    216: {"code": "F43", "desc": "Outdoor defrost temperature sensor abnormality"},
    222: {"code": "H95", "desc": "Indoor / outdoor wrong connection"},
    224: {"code": "H15", "desc": "Outdoor compressor temperature sensor abnormality"},
    225: {
        "code": "H23",
        "desc": "Indoor refrigerant liquid temperature sensor abnormality",
    },
    226: {"code": "H24", "desc": "Unknown"},
    227: {"code": "H38", "desc": "Indoor / outdoor mismatch"},
    228: {"code": "H61", "desc": "Unknown"},
    229: {"code": "H62", "desc": "Water flow switch abnormality"},
    230: {"code": "H63", "desc": "Refrigerant low pressure abnormality"},
    231: {"code": "H64", "desc": "Refrigerant high pressure abnormality"},
    232: {"code": "H42", "desc": "Compressor low pressure abnormality"},
    233: {"code": "H98", "desc": "Outdoor high pressure overload protection"},
    234: {"code": "F25", "desc": "Cooling / heating cycle changeover abnormality"},
    235: {"code": "F95", "desc": "Cooling high pressure overload protection"},
    236: {"code": "H70", "desc": "Indoor backup heater OLP abnormality"},
    237: {"code": "F48", "desc": "Outdoor EVA outlet temperature sensor abnormality"},
    238: {
        "code": "F49",
        "desc": "Outdoor bypass outlet temperature sensor abnormality",
    },
    65535: {"code": "N/A", "desc": "Communication error between PA-IntesisHome"},
}

API_URL = {
    DEVICE_AIRCONWITHME: "https://user.airconwithme.com/api.php/get/control",
    DEVICE_ANYWAIR: "https://anywair.intesishome.com/api.php/get/control",
    DEVICE_INTESISHOME: "https://user.intesishome.com/api.php/get/control",
}

API_VER = {
    DEVICE_AIRCONWITHME: "1.6.2",
    DEVICE_ANYWAIR: "2.9",
    DEVICE_INTESISHOME: "1.2.2",
}

LOCAL_CMD_LOGIN = "login"
LOCAL_CMD_GET_INFO = "getinfo"
LOCAL_CMD_SET_DP_VALUE = "setdatapointvalue"
LOCAL_CMD_GET_DP_VALUE = "getdatapointvalue"
LOCAL_CMD_GET_AVAIL_DP = "getavailabledatapoints"


INTESISBOX_CMD_GET_INFO = "ID"
INTESISBOX_CMD_GET_AVAIL_DP = "GET,1:*"
INTESISBOX_CMD_ONOFF = "ONOFF"
INTESISBOX_CMD_MODE = "MODE"
INTESISBOX_CMD_SETPOINT = "SETPTEMP"
INTESISBOX_CMD_FANSP = "FANSP"
INTESISBOX_CMD_VANEUD = "VANEUD"
INTESISBOX_CMD_VANELR = "VANELR"
INTESISBOX_CMD_AMBTEMP = "AMBTEMP"
INTESISBOX_CMD_ERRSTATUS = "ERRSTATUS"
INTESISBOX_CMD_ERRCODE = "ERRCODE"

INTESISBOX_CMD_MAP = {}

INTESISBOX_MODE_MAP = {
    "auto": "AUTO",
    "heat": "HEAT",
    "dry": "DRY",
    "fan": "FAN",
    "cool": "COOL",
}

INTESISBOX_MAP = {
    INTESISBOX_CMD_ONOFF: "power",
    INTESISBOX_CMD_MODE: "mode",
    INTESISBOX_CMD_SETPOINT: "setpoint",
    INTESISBOX_CMD_FANSP: "fan_speed",
    INTESISBOX_CMD_VANEUD: "vvane",
    INTESISBOX_CMD_VANELR: "hvane",
    INTESISBOX_CMD_AMBTEMP: "temperature",
    INTESISBOX_CMD_ERRSTATUS: "error_status",
    INTESISBOX_CMD_ERRCODE: "error_code",
}


INTESISBOX_INIT = [
    "ID",
    "LIMITS:SETPTEMP",
    "LIMITS:FANSP",
    "LIMITS:MODE",
    "LIMITS:VANEUD",
    "LIMITS:VANELR",
    "GET,1:ONOFF",
    "GET,1:MODE",
    "GET,1:AMBTEMP",
    "GET,1:SETPTEMP",
]
