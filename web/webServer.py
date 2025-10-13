#!/usr/bin/env/python
# File name   : server.py
# Production  : picar-b
# Website     : www.adeept.com
# Author      : devin

import time
import threading
from concurrent.futures import ThreadPoolExecutor
import logging
import move
import os
import info
import RPIservo

import functions
import robotLight
import switch
import buzzer
import pwm_led
import battery_monitor
import servo_calibration
import socket

#websocket
import asyncio
import websockets

import json
import app

OLED_connection = 0


functionMode = 0
speed_set = 100
rad = 0.5
turnWiggle = 60

SHOULDER_SERVO_CHANNEL = 0
SHOULDER_DRIVE_SPEED = 2

logger = logging.getLogger("rasptank")

_COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=1)

scGear = RPIservo.ServoCtrl()
# scGear.setup()
scGear.moveInit()

P_sc = RPIservo.ServoCtrl()
P_sc.start()
P_sc.set_direction(2, -1)

T_sc = RPIservo.ServoCtrl()
T_sc.start()

H1_sc = RPIservo.ServoCtrl()
H1_sc.start()
H1_sc.set_direction(0, -1)
H1_sc.set_relax_enabled(SHOULDER_SERVO_CHANNEL, False)

H2_sc = RPIservo.ServoCtrl()
H2_sc.start()

G_sc = RPIservo.ServoCtrl()
G_sc.start()
G_sc.set_direction(3, -1)

def _clamp_speed(value, minimum=1, maximum=10):
    return max(minimum, min(maximum, value))

ARM_SERVO_SPEED = _clamp_speed(int(os.getenv("ARM_SERVO_SPEED", "10")))


def _clamp_angle(value, minimum=0, maximum=180):
    return max(minimum, min(maximum, value))


_shoulder_calibration = {
    "base_angle": 90.0,
    "raise_angle": 45.0,
}


def _apply_shoulder_calibration(calibration):
    global _shoulder_calibration
    if not isinstance(calibration, dict):
        return
    base = _clamp_angle(float(calibration.get("base_angle", 90.0)))
    raise_angle = _clamp_angle(float(calibration.get("raise_angle", 45.0)))
    max_angle = max(0.0, min(180.0, base + raise_angle))
    min_angle = max(0.0, min(180.0, base))
    if max_angle < min_angle:
        max_angle = min_angle
    _shoulder_calibration = {
        "base_angle": base,
        "raise_angle": raise_angle,
    }

    try:
        target = int(round(base))
        H1_sc.initConfig(SHOULDER_SERVO_CHANNEL, target, 1)
        H1_sc.maxPos[SHOULDER_SERVO_CHANNEL] = int(round(max_angle))
        H1_sc.minPos[SHOULDER_SERVO_CHANNEL] = int(round(min_angle))
        H1_sc.goalPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.nowPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.lastPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.bufferPos[SHOULDER_SERVO_CHANNEL] = float(target)
        H1_sc.stopWiggle()
        _log_shoulder_state("shoulder_calibrated", target=target)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error({"evt": "shoulder_calibration_error", "error": str(exc)})


servo_calibration.register_shoulder_observer(_apply_shoulder_calibration)
_apply_shoulder_calibration(servo_calibration.get_shoulder_calibration())


# modeSelect = 'none'
modeSelect = 'PT'

init_pwm0 = scGear.initPos[0]
init_pwm1 = scGear.initPos[1]
init_pwm2 = scGear.initPos[2]
init_pwm3 = scGear.initPos[3]
init_pwm4 = scGear.initPos[4]

fuc = functions.Functions()
fuc.setup()
fuc.start()

curpath = os.path.realpath(__file__)
thisPath = "/" + os.path.dirname(curpath)

direction_command = 'no'
turn_command = 'no'
battery = None

def log_servo_action(action, **extra):
    payload = {"evt": "servo_action", "action": action}
    payload.update(extra)
    logger.info(payload)

def log_led_action(action, **extra):
    payload = {"evt": "led_action", "action": action}
    payload.update(extra)
    logger.info(payload)

def servoPosInit():
    scGear.initConfig(0,init_pwm0,1)
    P_sc.initConfig(1,init_pwm1,1)
    T_sc.initConfig(2,init_pwm2,1)
    H1_sc.initConfig(3,init_pwm3,1)
    H2_sc.initConfig(3,init_pwm3,1)
    G_sc.initConfig(4,init_pwm4,1)


def replace_num(initial,new_num):   #Call this function to replace data in '.txt' file
    global r
    newline=""
    str_num=str(new_num)
    with open(thisPath+"/RPIservo.py","r") as f:
        for line in f.readlines():
            if(line.find(initial) == 0):
                line = initial+"%s" %(str_num+"\n")
            newline += line
    with open(thisPath+"/RPIservo.py","w") as f:
        f.writelines(newline)


# def FPV_thread():
#     global fpv
#     fpv=FPV.FPV()
#     fpv.capture_thread(addr[0])


def ap_thread():
    os.system("sudo create_ap wlan0 eth0 Adeept_Robot 12345678")


def functionSelect(command_input, response):
    global functionMode

    if 'findColor' == command_input:
        flask_app.modeselect('findColor')

    if 'motionGet' == command_input:
        flask_app.modeselect('watchDog')

    elif 'stopCV' == command_input:
        flask_app.modeselect('none')
        switch.switch(1,0)
        switch.switch(2,0)
        switch.switch(3,0)
        move.motorStop()

    elif 'KD' == command_input:
        servoPosInit()
        fuc.keepDistance()
        if WS2812_mark:
            WS2812.police()

    elif 'police' == command_input:
        if WS2812_mark:
            WS2812.police()

    elif 'policeOff' == command_input:
        if WS2812_mark:
            WS2812.breath(70,70,255)

    elif 'automatic' == command_input:
        if modeSelect == 'PT':
            fuc.automatic()
        else:
            fuc.pause()

    elif 'automaticOff' == command_input:
        if WS2812_mark:
            WS2812.pause()
        fuc.pause()
        move.motorStop()
        time.sleep(0.3)
        move.motorStop()

    elif 'trackLine' == command_input:
        servoPosInit()
        fuc.trackLine()

    elif 'trackLineOff' == command_input:
        fuc.pause()
        move.motorStop()

    elif 'steadyCamera' == command_input:
        fuc.steady(T_sc.lastPos[2])

    elif 'steadyCameraOff' == command_input:
        fuc.pause()
        move.motorStop()




def switchCtrl(command_input, response):
    if 'Switch_1_on' in command_input:
        switch.switch(1,1)

    elif 'Switch_1_off' in command_input:
        switch.switch(1,0)

    elif 'Switch_2_on' in command_input:
        switch.switch(2,1)

    elif 'Switch_2_off' in command_input:
        switch.switch(2,0)

    elif 'Switch_3_on' in command_input:
        log_led_action('Switch_3_on')
        switch.switch(3,1)

    elif 'Switch_3_off' in command_input:
        log_led_action('Switch_3_off')
        switch.switch(3,0) 

    elif 'ledOn' == command_input:
        log_led_action('ledOn')
        pwm_led.turn_on()
        buzzer.tick()

    elif 'ledOff' == command_input:
        log_led_action('ledOff')
        pwm_led.turn_off()
        buzzer.tick()


def robotCtrl(command_input, response):
    global direction_command, turn_command
    if 'forward' == command_input:
        direction_command = 'forward'
        move.move(speed_set, 1, "mid")
        buzzer.tick()
        logger.debug({"evt": "drive_debug", "note": "forward command tick"})
    
    elif 'backward' == command_input:
        direction_command = 'backward'
        move.move(speed_set, -1, "no")
        buzzer.tick()

    elif 'DS' in command_input:
        direction_command = 'no'
        if turn_command == 'no':
            move.motorStop()


    elif 'left' == command_input:
        turn_command = 'left'
        move.move(speed_set, 1, "left")
        buzzer.tick()

    elif 'right' == command_input:
        turn_command = 'right'
        move.move(speed_set, 1, "right")
        buzzer.tick()


    elif 'TS' in command_input:
        turn_command = 'no'
        if direction_command == 'no':
            move.motorStop()

    elif 'armUp' == command_input: #servo A
        log_servo_action('armUp')
        H1_sc.singleServo(SHOULDER_SERVO_CHANNEL, -1, SHOULDER_DRIVE_SPEED)
        _log_shoulder_state("shoulder_cmd", direction="up")
    elif 'armDown' == command_input:
        log_servo_action('armDown')
        H1_sc.singleServo(SHOULDER_SERVO_CHANNEL, 1, SHOULDER_DRIVE_SPEED)
        _log_shoulder_state("shoulder_cmd", direction="down")
    elif 'armStop' in command_input:
        log_servo_action('armStop')
        H1_sc.stopWiggle()
        _log_shoulder_state("shoulder_cmd", direction="stop")

    elif 'handUp' == command_input: # servo B
        log_servo_action('handUp')
        H2_sc.singleServo(1, -1, 2)
    elif 'handDown' == command_input:
        log_servo_action('handDown')
        H2_sc.singleServo(1,1, 2)
    elif 'handStop' in command_input:
        log_servo_action('handStop')
        H2_sc.stopWiggle()

    elif 'lookleft' == command_input: # servo C
        log_servo_action('lookleft')
        P_sc.singleServo(2, 1, 2)
    elif 'lookright' == command_input:
        log_servo_action('lookright')
        P_sc.singleServo(2,-1, 2)
    elif 'LRstop' in command_input:
        log_servo_action('LRstop')
        P_sc.stopWiggle()

    elif 'grab' == command_input: # servo D
        log_servo_action('grab')
        G_sc.singleServo(3, 1, 2)
        buzzer.double()
    elif 'loose' == command_input:
        log_servo_action('loose')
        G_sc.singleServo(3,-1, 2)
        buzzer.double()
    elif 'GLstop' in command_input:
        log_servo_action('GLstop')
        G_sc.stopWiggle()

    elif 'up' == command_input: # camera
        log_servo_action('up')
        T_sc.singleServo(4, -1, 1)
    elif 'down' == command_input:
        log_servo_action('down')
        T_sc.singleServo(4,1, 1)
    elif 'UDstop' in command_input:
        log_servo_action('UDstop')
        T_sc.stopWiggle()



    elif 'home' == command_input:
        log_servo_action('home')
        H1_sc.moveServoInit(0)
        H2_sc.moveServoInit(1)
        P_sc.moveServoInit(2)
        G_sc.moveServoInit(3)
        T_sc.moveServoInit(4)
        logger.debug({"evt": "servo_home"})


def configPWM(command_input, response):
    global init_pwm0, init_pwm1, init_pwm2, init_pwm3, init_pwm4

    if 'SiLeft' in command_input:
        numServo = int(command_input[7:])
        if numServo == 0:
            init_pwm0 -= 1
            H1_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 -= 1
            H2_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 -= 1
            P_sc.setPWM(2,init_pwm2)
        elif numServo == 3:
            init_pwm3 -= 1
            G_sc.setPWM(3,init_pwm3)
        elif numServo == 4:
            init_pwm4 -= 1
            T_sc.setPWM(4,init_pwm4)

    if 'SiRight' in command_input:
        numServo = int(command_input[8:])
        if numServo == 0:
            init_pwm0 += 1
            T_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 += 1
            P_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 += 1
            scGear.setPWM(2,init_pwm2)

        if numServo == 0:
            init_pwm0 += 1
            H1_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 += 1
            H2_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 += 1
            P_sc.setPWM(2,init_pwm2)
        elif numServo == 3:
            init_pwm3 += 1
            G_sc.setPWM(3,init_pwm3)
        elif numServo == 4:
            init_pwm4 += 1
            T_sc.setPWM(4,init_pwm4)

    if 'PWMMS' in command_input:
        numServo = int(command_input[6:])
        if numServo == 0:
            T_sc.initConfig(0, init_pwm0, 1)
            replace_num('init_pwm0 = ', init_pwm0)
        elif numServo == 1:
            P_sc.initConfig(1, init_pwm1, 1)
            replace_num('init_pwm1 = ', init_pwm1)
        elif numServo == 2:
            scGear.initConfig(2, init_pwm2, 2)
            replace_num('init_pwm2 = ', init_pwm2)


    if 'PWMINIT' == command_input:
        logger.debug({"evt": "pwm_init_readback", "value": init_pwm1})
        servoPosInit()

    elif 'PWMD' == command_input:
        init_pwm0,init_pwm1,init_pwm2,init_pwm3,init_pwm4=90,90,90,90,90
        T_sc.initConfig(0,90,1)
        replace_num('init_pwm0 = ', 90)

        P_sc.initConfig(1,90,1)
        replace_num('init_pwm1 = ', 90)

        scGear.initConfig(2,90,1)
        replace_num('init_pwm2 = ', 90)


def _process_hardware_command(command_input: str) -> None:
    try:
        logger.info({"evt": "command_queue", "cmd": command_input})
        robotCtrl(command_input, None)
        switchCtrl(command_input, None)
        functionSelect(command_input, None)
        configPWM(command_input, None)
    except Exception as exc:
        logger.error({"evt": "command_queue_error", "cmd": command_input, "error": str(exc)})


def _dispatch_hardware_command(command_input: str) -> None:
    _COMMAND_EXECUTOR.submit(_process_hardware_command, command_input)


def _log_shoulder_state(event: str, **extra) -> None:
    try:
        now_pos = H1_sc.nowPos[SHOULDER_SERVO_CHANNEL]
        goal_pos = H1_sc.goalPos[SHOULDER_SERVO_CHANNEL]
        speed = H1_sc.scSpeed[SHOULDER_SERVO_CHANNEL]
    except Exception:
        now_pos = goal_pos = speed = None
    telemetry = {
        "evt": event,
        "servo": "shoulder",
        "channel": SHOULDER_SERVO_CHANNEL,
        "now": now_pos,
        "goal": goal_pos,
        "speed": speed,
        "calibration": dict(_shoulder_calibration),
    }
    if battery is not None:
        try:
            telemetry["vbat"] = round(battery.read_voltage(), 2)
            telemetry["vbat_pct"] = battery.read_percentage()
        except Exception as exc:
            telemetry["vbat_error"] = str(exc)
    telemetry.update(extra)
    logger.info(telemetry)


def update_code():
    # Update local to be consistent with remote
    projectPath = thisPath[:-7]
    with open(f'{projectPath}/config.json', 'r') as f1:
        config = json.load(f1)
        if not config['production']:
            logger.info({"evt": "update_code", "status": "starting"})
            # Force overwriting local code
            if os.system(f'cd {projectPath} && sudo git fetch --all && sudo git reset --hard origin/master && sudo git pull') == 0:
                logger.info({"evt": "update_code", "status": "completed"})
                logger.info({"evt": "system", "action": "reboot"})
                os.system('sudo reboot')
            
def wifi_check():
    try:
        s =socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("1.1.1.1",80))
        ipaddr_check=s.getsockname()[0]
        s.close()
        logger.info({"evt": "network_ip", "ip": ipaddr_check})
    except:
        ap_threading=threading.Thread(target=ap_thread)   #Define a thread for data receiving
        ap_threading.setDaemon(True)                          #'True' means it is a front thread,it would close when the mainloop() closes
        ap_threading.start()                                  #Thread starts
        if WS2812_mark:
            WS2812.setColor(0,16,50)
        time.sleep(1)

async def check_permit(websocket):
    while True:
        recv_str = await websocket.recv()
        cred_dict = recv_str.split(":")
        if cred_dict[0] == "admin" and cred_dict[1] == "123456":
            response_str = "congratulation, you have connect with server\r\nnow, you can do something else"
            await websocket.send(response_str)
            return True
        else:
            response_str = "sorry, the username or password is wrong, please submit again"
            await websocket.send(response_str)

async def recv_msg(websocket):
    global speed_set, modeSelect, battery

    while True: 
        response = {
            'status' : 'ok',
            'title' : '',
            'data' : None
        }

        data = ''
        data = await websocket.recv()
        try:
            data = json.loads(data)
        except Exception as e:
            logger.debug({"evt": "ws_parse_failed", "raw": data})

        if not data:
            continue

        if isinstance(data,str):
            handled_locally = False

            if data == 'get_info':
                response['title'] = 'get_info'
                cpu_temp = info.get_cpu_tempfunc()
                cpu_use = info.get_cpu_use()
                ram_info = info.get_ram_info()
                voltage = 0.0
                percentage = 0
                if battery is not None:
                    try:
                        voltage = round(battery.read_voltage(), 2)
                        percentage = battery.read_percentage()
                    except Exception as exc:
                        logger.warning({"evt": "battery_read_error", "error": str(exc)})
                response['data'] = [cpu_temp, cpu_use, ram_info, voltage, percentage]
                handled_locally = True

            elif data.startswith('wsB'):
                try:
                    set_B = data.split()
                    speed_set = int(set_B[1])
                except Exception:
                    logger.debug({"evt": "speed_set_parse_failed", "raw": data})
                handled_locally = True

            # CVFL commands are lightweight camera tweaks; keep them inline.
            elif data == 'CVFL':
                flask_app.modeselect('findlineCV')
                handled_locally = True

            elif data.startswith('CVFLColorSet'):
                try:
                    color = int(data.split()[1])
                    flask_app.camera.colorSet(color)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_color_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLL1'):
                try:
                    pos = int(data.split()[1])
                    flask_app.camera.linePosSet_1(pos)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_line1_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLL2'):
                try:
                    pos = int(data.split()[1])
                    flask_app.camera.linePosSet_2(pos)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_line2_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLSP'):
                try:
                    err = int(data.split()[1])
                    flask_app.camera.errorSet(err)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_err_error", "error": str(exc)})
                handled_locally = True

            if not handled_locally and data:
                _dispatch_hardware_command(data)
                response['status'] = 'queued'


        elif(isinstance(data,dict)):
            if data['title'] == "findColorSet":
                color = data['data']
                flask_app.colorFindSet(color[0],color[1],color[2])

        logger.debug({"evt": "ws_command_processed", "payload": data})
        response = json.dumps(response)
        await websocket.send(response)

async def main_logic(websocket, path):
    await check_permit(websocket)
    await recv_msg(websocket)

if __name__ == '__main__':
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s %(levelname)s %(message)s',
    )
    logger.info({"evt": "startup", "component": "webServer", "log_level": log_level})

    switch.switchSetup()
    switch.set_all_switch_off()
    
    move.setup()
    WS2812_mark = None

    HOST = ''
    PORT = 10223                              #Define port serial 
    BUFSIZ = 1024                             #Define buffer size
    ADDR = (HOST, PORT)

    global flask_app
    flask_app = app.webapp()
    flask_app.startthread()

    battery = battery_monitor.BatteryMonitor()
    battery.start()

    buzzer.alert()

    try:
        # global WS2812
        robotlight_check = robotLight.check_rpi_model()
        if robotlight_check == 5:
            logger.warning({"evt": "ws2812_unsupported_pi5"})
            WS2812_mark = 0 # WS2812 not compatible
        else:
            logger.info({"evt": "ws2812_init", "status": "ok"})
            WS2812_mark = 1
            WS2812=robotLight.RobotWS2812()
            WS2812.start()
            WS2812.breath(70,70,255)
    except Exception as exc:
        logger.warning({"evt": "ws2812_missing_dependency", "hint": "pip install rpi_ws281x", "error": str(exc)})
        pass

    while  1:
        wifi_check()
        try:                  #Start server,waiting for client
            start_server = websockets.serve(main_logic, '0.0.0.0', 8888)
            asyncio.get_event_loop().run_until_complete(start_server)
            logger.info({"evt": "ws_server", "status": "waiting"})
            # print('...connected from :', addr)
            break
        except Exception as e:
            logger.error({"evt": "ws_server_error", "error": str(e)})
            if WS2812_mark:
                WS2812.setColor(0,0,0)
            else:
                pass

        try:
            if WS2812_mark == 1:
                WS2812.setColor(0,80,255)
            else:
                pass
        except:
            pass
    try:
        asyncio.get_event_loop().run_forever()
    except Exception as e:
        logger.error({"evt": "ws_loop_error", "error": str(e)})
        if WS2812_mark:
            WS2812.setColor(0,0,0)
        else:
            pass
        move.destroy()
