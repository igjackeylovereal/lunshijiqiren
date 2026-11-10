#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Explicit-port Modbus base I/O with ACK, readback and local command timeout."""
from __future__ import division
import ctypes as C
import json
import math
import os
import struct
import subprocess
import threading
import time


def encode_speeds(speeds):
    if len(speeds) != 3 or not all(not math.isnan(v) and not math.isinf(v) for v in speeds):
        raise ValueError('three finite speeds required')
    words = []
    for value in speeds:
        words.extend(struct.unpack('>4H', struct.pack('>d', value)))
    return words + [0]


def decode_speed(words):
    if len(words) != 4:
        raise ValueError('four registers required')
    value = struct.unpack('>d', struct.pack('>4H', *words))[0]
    if math.isnan(value) or math.isinf(value):
        raise ValueError('nonfinite wheel speed')
    return value


def effective_command(command, age, readonly=False, fault=False):
    if readonly or fault or not 0 <= age <= .25:
        return (0., 0., 0.)
    if len(command) < 2 or not all(not math.isnan(v) and not math.isinf(v) for v in command[:2]):
        return (0., 0., 0.)
    return (max(-30., min(30., command[0])), max(-30., min(30., command[1])), 0.)


def velocity_to_rpm(vx, wz, radius=.068, separation=.32374):
    if not all(not math.isnan(v) and not math.isinf(v) for v in (vx, wz)):
        return (0., 0., 0.)
    return (-(vx-wz*separation/2)/radius*30/math.pi,
            (vx+wz*separation/2)/radius*30/math.pi, 0.)


class ModbusLink(object):
    def __init__(self, port):
        with open(os.devnull, 'w') as null:
            if subprocess.call(['fuser', port], stdout=null, stderr=null) != 1:
                raise ValueError('base port in use or ownership cannot be checked')
        path = os.path.expanduser('~/bobac2_ws/src/bobac2_base/modbus/lib/libmodbus.so.5.1.0')
        self.lib = C.CDLL(path, use_errno=True)
        pointer, registers = C.c_void_p, C.POINTER(C.c_uint16)
        definitions = {
            'modbus_new_rtu': ([C.c_char_p, C.c_int, C.c_char, C.c_int, C.c_int], pointer),
            'modbus_set_slave': ([pointer, C.c_int], C.c_int),
            'modbus_connect': ([pointer], C.c_int),
            'modbus_get_socket': ([pointer], C.c_int),
            'modbus_set_response_timeout': ([pointer, C.c_uint32, C.c_uint32], C.c_int),
            'modbus_read_input_registers': ([pointer, C.c_int, C.c_int, registers], C.c_int),
            'modbus_read_registers': ([pointer, C.c_int, C.c_int, registers], C.c_int),
            'modbus_write_registers': ([pointer, C.c_int, C.c_int, registers], C.c_int),
            'modbus_close': ([pointer], None), 'modbus_free': ([pointer], None),
            'modbus_strerror': ([C.c_int], C.c_char_p)}
        for name, (args, result) in definitions.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.ctx = self.lib.modbus_new_rtu(port.encode('ascii'), 115200, b'N', 8, 1)
        if not self.ctx:
            raise ValueError('cannot create Modbus context')
        self.lib.modbus_set_slave(self.ctx, 1)
        if self.lib.modbus_connect(self.ctx) != 0:
            self.close()
            raise ValueError('cannot connect base serial port')
        self.lib.modbus_set_response_timeout(self.ctx, 0, 150000)
        import fcntl
        import termios
        fcntl.ioctl(self.lib.modbus_get_socket(self.ctx), termios.TIOCEXCL)

    def read(self, count, holding=False):
        data = (C.c_uint16 * count)()
        function = self.lib.modbus_read_registers if holding else self.lib.modbus_read_input_registers
        result = function(self.ctx, 0, count, data)
        if result != count:
            raise ValueError(self.lib.modbus_strerror(C.get_errno()).decode('utf-8', 'replace'))
        return list(data)

    def write(self, speeds):
        values = encode_speeds(speeds)
        data = (C.c_uint16 * 13)(*values)
        result = self.lib.modbus_write_registers(self.ctx, 0, 13, data)
        if result != 13:
            raise ValueError(self.lib.modbus_strerror(C.get_errno()).decode('utf-8', 'replace'))
        return result

    def close(self):
        if self.ctx:
            self.lib.modbus_close(self.ctx)
            self.lib.modbus_free(self.ctx)
            self.ctx = None


def main():
    import rospy
    from std_msgs.msg import String
    from geometry_msgs.msg import Twist
    from bobac2_msgs.msg import car_data, car_cmd
    rospy.init_node('bobac2_base_node')
    port = rospy.get_param('~serial_port', '/dev/ttyS0')
    readonly = rospy.get_param('~read_only', True)
    # This port was verified on this robot. Never scan unrelated serial devices.
    if port != '/dev/ttyS0':
        raise ValueError('explicitly verified base port /dev/ttyS0 required')
    link = ModbusLink(port)
    data_pub = rospy.Publisher('/car_data', car_data, queue_size=5)
    status_pub = rospy.Publisher('/practicum_base/io_status', String, queue_size=2)
    command_pub = rospy.Publisher('/car_cmd', car_cmd, queue_size=1) if not readonly else None
    latest = dict(command=(0., 0., 0.), time=0.)
    lock = threading.Lock()

    def command(message):
        values = velocity_to_rpm(message.linear.x, message.angular.z)
        with lock:
            latest.update(command=values, time=time.time())

    if not readonly:
        rospy.Subscriber('cmd_vel', Twist, command, queue_size=1)
    fault, last_applied, last_write, last_status = '', None, 0., 0.
    write_ok, readback = False, [0., 0., 0.]
    rate = rospy.Rate(50)
    event_path = os.path.expanduser('~/bobac_practicum_run/maps/base_command_events.jsonl')
    if not os.path.isdir(os.path.dirname(event_path)):
        os.makedirs(os.path.dirname(event_path), 0o700)
    try:
        while not rospy.is_shutdown():
            now = time.time()
            with lock:
                requested, age = latest['command'], now-latest['time']
            applied = effective_command(requested, age, readonly, bool(fault))
            try:
                if not readonly and (applied != last_applied or now-last_write >= .08):
                    changed = applied != last_applied
                    link.write(applied)
                    diagnostic = car_cmd()
                    diagnostic.speed = list(applied[:2])
                    command_pub.publish(diagnostic)
                    write_ok, last_write = True, now
                    if changed:
                        raw = link.read(13, holding=True)
                        readback = [decode_speed(raw[i:i+4]) for i in (0, 4, 8)]
                        if any(abs(a-b) > 1e-6 for a, b in zip(applied, readback)):
                            raise ValueError('firmware target readback mismatch')
                        with open(event_path, 'a') as stream:
                            stream.write(json.dumps(dict(time=now, requested=requested, applied=applied,
                                readback=readback, ack=True)) + '\n')
                    last_applied = applied
                raw = link.read(49)
                message = car_data()
                message.speed = [decode_speed(raw[i:i+4]) for i in (0, 4, 8)]
                message.crash, message.infrared, message.ultrasonic = raw[12:15], raw[15:18], raw[18:24]
                message.smoke, message.power_voltage = raw[24], raw[25]
                message.mpu = [struct.unpack('>f', struct.pack('>2H', *raw[i:i+2]))[0] for i in range(26, 44, 2)]
                message.tempareture = struct.unpack('>f', struct.pack('>2H', *raw[44:46]))[0]
                message.humidity = struct.unpack('>f', struct.pack('>2H', *raw[46:48]))[0]
                data_pub.publish(message)
                if now-last_status >= .1:
                    status_pub.publish(String(data=json.dumps(dict(time=now, port=port, read_only=readonly,
                        write_ok=write_ok, fault=fault, requested=requested, applied=applied,
                        readback=readback, actual=message.speed, infrared=message.infrared,
                        crash=message.crash))))
                    last_status = now
            except Exception as exc:
                fault, write_ok = str(exc), False
                if not readonly:
                    try: link.write((0., 0., 0.))
                    except Exception: pass
                status_pub.publish(String(data=json.dumps(dict(time=time.time(), write_ok=False, fault=fault))))
                rospy.logerr_throttle(3, fault)
            rate.sleep()
    finally:
        if not readonly:
            try: link.write((0., 0., 0.))
            except Exception: pass
        link.close()


if __name__ == '__main__':
    main()
