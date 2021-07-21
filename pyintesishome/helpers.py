""" Helpers for pyintesishome """


def twos_complement_16bit(val):
    """Compute Two's Complement, to represent negative temperatures"""
    if (val & (1 << 15)) != 0:
        val = val - (1 << 16)
    return val


def uint32(value):
    """uint32"""
    result = int(value) & 0xFFFF
    return result
