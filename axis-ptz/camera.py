#!/usr/bin/env python3



import argparse
import threading
import json
import sys
import os
import calendar
from datetime import datetime, timedelta
import signal
import random
import time
import re
import requests
from requests.auth import HTTPDigestAuth
import errno
import paho.mqtt.client as mqtt 
from json.decoder import JSONDecodeError
from sensecam_control import vapix_control,vapix_config

import logging
import coloredlogs
import logging.config # This gets rid of the annoying log messages from Vapix_Control
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})
logging.getLogger("vapix_control.py").setLevel(logging.WARNING)
logging.getLogger("vapix_control").setLevel(logging.WARNING)
logging.getLogger("sensecam_control").setLevel(logging.WARNING)

ID = str(random.randint(1,100001))
args = None
camera = None
cameraConfig = None
cameraZoom = None
cameraMoveSpeed = None
cameraDelay = None


object_topic = None
flight_topic = None
config_topic = "skyscan/config/json"

bearing = 0         # this is an angle
elevation = 0       # this is an angle
cameraPan = 0   # This value is in angles and corrects for the camera not being level
cameraTilt = 0 # This values is in angles and corrects for the camera not being level
distance3d = 0      # this is in Meters
planeTrack = 0    # This is the direction that the plane is moving in

actualCameraPan = 0
actualCameraTilt = 0
follow_x = 0
follow_y = 0
actualX = 0
actualY = 0
currentPlane=None
object_timeout=0

# https://stackoverflow.com/questions/45659723/calculate-the-difference-between-two-compass-headings-python

# The camera hat takes bearings between -90 and 90. 
# h1 is the target heading
# h2 is the heading the camera is pointed at
def getHeadingDiff(h1, h2):
    if h1 > 360 or h1 < 0 or h2 > 360 or h2 < 0:
        raise Exception("out of range")
    diff = h1 - h2
    absDiff = abs(diff)

    if absDiff == 180:
        return absDiff
    elif absDiff < 180:
        return diff
    elif h2 > h1:
        return 360 - absDiff
    else:
        return absDiff - 360

def setXY(x,y):
    global follow_x
    global follow_y

    follow_x = int(x)
    follow_y = int(y)
    

def setCameraPan(newPan):
    global cameraPan
    #diff_heading = getHeadingDiff(cameraPan, cameraPan)
    

    if newPan != cameraPan: #cameraPan #abs(cameraPan - diff_heading) > 2: #only update the cameraPan if there has been a big change
        #logging.info("Heading Diff %d for Bearing %d & Camera Bearing: %d"% (diff_heading, cameraPan, cameraPan))

        cameraPan = newPan
        #logging.info("Setting Bearing to: %d"%cameraPan)
            
        return True
    return False

def setCameraTilt(newTilt):
    global cameraTilt
    if newTilt < 90:
        if cameraTilt != newTilt: 
            cameraTilt = newTilt
            
            #logging.info("Setting Elevation to: %d"%cameraTilt)

 # Copied from VaPix/Sensecam to customize the folder structure for saving pictures          
def get_jpeg_request():  # 5.2.4.1
    """
    The requests specified in the JPEG/MJPG section are supported by those video products
    that use JPEG and MJPG encoding.
    Args:
        resolution: Resolution of the returned image. Check the product’s Release notes.
        camera: Selects the source camera or the quad stream.
        square_pixel: Enable/disable square pixel correction. Applies only to video encoders.
        compression: Adjusts the compression level of the image.
        clock: Shows/hides the time stamp. (0 = hide, 1 = show)
        date: Shows/hides the date. (0 = hide, 1 = show)
        text: Shows/hides the text. (0 = hide, 1 = show)
        text_string: The text shown in the image, the string must be URL encoded.
        text_color: The color of the text shown in the image. (black, white)
        text_background_color: The color of the text background shown in the image.
        (black, white, transparent, semitransparent)
        rotation: Rotate the image clockwise.
        text_position: The position of the string shown in the image. (top, bottom)
        overlay_image: Enable/disable overlay image.(0 = disable, 1 = enable)
        overlay_position:The x and y coordinates defining the position of the overlay image.
        (<int>x<int>)
    Returns:
        Success ('image save' and save the image in the file folder) or Failure (Error and
        description).
    """
    payload = {
        'resolution': "1920x1080",
        'compression': 0,
        'camera': 5,
    }
    url = 'http://' + args.axis_ip + '/axis-cgi/jpg/image.cgi'
    start_time = datetime.now()
    try:
        resp = requests.get(url, auth=HTTPDigestAuth(
            args.axis_username, args.axis_password), params=payload, timeout=0.2)
    except requests.exceptions.Timeout:
        logging.info("We timed out")

    disk_time = datetime.now()
    if resp.status_code == 200:
        captureDir = "capture/{}".format(currentPlane["type"])
        try:
            os.makedirs(captureDir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise  # This was not a "directory exist" error..
        filename = "{}/{}_{}_{}_{}_{}.jpg".format(captureDir, currentPlane["icao24"], int(
            bearing), int(elevation), int(distance3d), datetime.now().strftime('%Y-%m-%d-%H-%M-%S'))

        # Original
        #with open(filename, 'wb') as var:
        #    var.write(resp.content)

        #Non-Blocking
        #fd = os.open(filename, os.O_CREAT | os.O_WRONLY | os.O_NONBLOCK)
        #os.write(fd, resp.content)
        #os.close(fd)

        # Blocking

        fd = os.open(filename, os.O_CREAT | os.O_WRONLY)
        os.write(fd, resp.content)
        os.close(fd)


    end_time = datetime.now()
    net_time_diff = (disk_time - start_time)
    disk_time_diff = (end_time - disk_time)
    if disk_time_diff.total_seconds() > 0.1:
        logging.info("🚨  Image Capture Timeout  🚨  Net time: {}  \tDisk time: {}".format(net_time_diff, disk_time_diff))




def get_bmp_request():  # 5.2.4.1
    """
    The requests specified in the JPEG/MJPG section are supported by those video products
    that use JPEG and MJPG encoding.
    Args:
        resolution: Resolution of the returned image. Check the product’s Release notes.
        camera: Selects the source camera or the quad stream.
        square_pixel: Enable/disable square pixel correction. Applies only to video encoders.
        compression: Adjusts the compression level of the image.
        clock: Shows/hides the time stamp. (0 = hide, 1 = show)
        date: Shows/hides the date. (0 = hide, 1 = show)
        text: Shows/hides the text. (0 = hide, 1 = show)
        text_string: The text shown in the image, the string must be URL encoded.
        text_color: The color of the text shown in the image. (black, white)
        text_background_color: The color of the text background shown in the image.
        (black, white, transparent, semitransparent)
        rotation: Rotate the image clockwise.
        text_position: The position of the string shown in the image. (top, bottom)
        overlay_image: Enable/disable overlay image.(0 = disable, 1 = enable)
        overlay_position:The x and y coordinates defining the position of the overlay image.
        (<int>x<int>)
    Returns:
        Success ('image save' and save the image in the file folder) or Failure (Error and
        description).
    """
    payload = {
        'resolution': "1920x1080",
        'camera': 1,
    }
    url = 'http://' + args.axis_ip + '/axis-cgi/bitmap/image.bmp'
    resp = requests.get(url, auth=HTTPDigestAuth(args.axis_username, args.axis_password),
                        params=payload)

    if resp.status_code == 200:
        captureDir = "capture/{}".format(currentPlane["type"])
        try:
            os.makedirs(captureDir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise  # This was not a "directory exist" error..
        filename = "{}/{}_{}_{}_{}_{}.bmp".format(captureDir,currentPlane["icao24"],int(bearing),int(elevation),int(distance3d),datetime.now().strftime('%Y-%m-%d-%H-%M-%S'))
        
        with open(filename, 'wb') as var:
            var.write(resp.content)
        return str('Image saved')

    text = str(resp)
    text += str(resp.text)
    return text

def moveCamera():
    global actualCameraPan
    global actualCameraTilt
    global actualX
    global actualY
    global camera

    
    while True:
        lockedOn = False
        if (object_timeout < time.mktime(time.gmtime())):
            if actualCameraTilt != cameraTilt or actualCameraPan != cameraPan:
                actualCameraTilt = cameraTilt
                actualCameraPan = cameraPan
                lockedOn = True
                camera.absolute_move(cameraPan, cameraTilt, cameraZoom, cameraMoveSpeed)
                time.sleep(cameraDelay)
                get_jpeg_request()
                #get_bmp_request()
        else:
            if actualX != follow_x or actualY != follow_y:
                actualX = follow_x
                actualY = follow_y
                #camera.center_move(actualX, actualY, cameraMoveSpeed)
                pan_tilt = str(actualX) + "," + str(actualY)
                camera._camera_command({'center': pan_tilt, 'speed': cameraMoveSpeed, 'imagewidth': '1280', 'imageheight': '720'})
                #time.sleep(cameraDelay)
        #if lockedOn == True:
        #    filename = "capture/{}_{}".format(datetime.now().strftime('%Y-%m-%d-%H-%M-%S'), currentPlane)
        #    camera.capture("{}.jpeg".format(filename))

        # Sleep for a bit so we're not hammering the camera withupdates
        time.sleep(0.005)


def update_config(config):
    global cameraZoom
    global cameraMoveSpeed
    global cameraDelay
    global cameraPan

    if "cameraZoom" in config:
        cameraZoom = int(config["cameraZoom"])
        logging.info("Setting Camera Zoom to: {}".format(cameraZoom))
    if "cameraDelay" in config:
        cameraDelay = float(config["cameraDelay"])
        logging.info("Setting Camera Delay to: {}".format(cameraDelay))
    if "cameraMoveSpeed" in config:
        cameraMoveSpeed = int(config["cameraMoveSpeed"])
        logging.info("Setting Camera Move Speed to: {}".format(cameraMoveSpeed))



#############################################
##         MQTT Callback Function          ##
#############################################
def on_message(client, userdata, message):
    global currentPlane
    global object_timeout
    global distance3d
    global bearing
    global elevation

    command = str(message.payload.decode("utf-8"))
    #rint(command)
    try:
        update = json.loads(command)
        #payload = json.loads(messsage.payload) # you can use json.loads to convert string to json
    except JSONDecodeError as e:
    # do whatever you want
        print(e)
    except TypeError as e:
    # do whatever you want in this case
        print(e)
    except ValueError as e:
        print(e)
    except:
        print("Caught it!")
    
    if message.topic == object_topic:
        logging.info("Got Object Topic")
        setXY(update["x"], update["y"])
        object_timeout = time.mktime(time.gmtime()) + 5
    elif message.topic == flight_topic:
        logging.info("{}\t[IMAGE]\tBearing: {} \tElv: {} \tPan: {} \tTilt: {} \tDist: {}".format(update["icao24"],int(update["bearing"]),int(update["elevation"]),int(update["cameraPan"]),int(update["cameraTilt"]),int(update["distance"])))
        distance3d = update["distance"]
        bearing = update["bearing"]
        elevation = update["elevation"]
        setCameraPan(update["cameraPan"])
        setCameraTilt(update["cameraTilt"])
        currentPlane = update
    elif message.topic == config_topic:
        update_config(update)
        logging.info("Config Message: {}".format(update))
    else:
        logging.info("Message: {} Object: {} Flight: {}".format(message.topic, object_topic, flight_topic))

def main():
    global args
    global logging
    global camera
    global cameraDelay
    global cameraMoveSpeed
    global cameraZoom
    global cameraPan
    global cameraConfig
    global flight_topic
    global object_topic

    parser = argparse.ArgumentParser(description='An MQTT based camera controller')

    parser.add_argument('-m', '--mqtt-host', help="MQTT broker hostname", default='127.0.0.1')
    parser.add_argument('-t', '--mqtt-flight-topic', help="MQTT topic to subscribe to", default="skyscan/flight/json")
    parser.add_argument( '--mqtt-object-topic', help="MQTT topic to subscribe to", default="skyscan/object/json")
    parser.add_argument('-u', '--axis-username', help="Username for the Axis camera", required=True)
    parser.add_argument('-p', '--axis-password', help="Password for the Axis camera", required=True)
    parser.add_argument('-a', '--axis-ip', help="IP address for the Axis camera", required=True)
    parser.add_argument('-s', '--camera-move-speed', type=int, help="The speed at which the Axis will move for Pan/Tilt (0-100)", default=50)
    parser.add_argument('-d', '--camera-delay', type=float, help="How many seconds after issuing a Pan/Tilt command should a picture be taken", default=0.5)
    parser.add_argument('-z', '--camera-zoom', type=int, help="The zoom setting for the camera (0-9999)", default=9999)
    parser.add_argument('-v', '--verbose',  action="store_true", help="Verbose output")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    
    styles = {'critical': {'bold': True, 'color': 'red'}, 'debug': {'color': 'green'}, 'error': {'color': 'red'}, 'info': {'color': 'white'}, 'notice': {'color': 'magenta'}, 'spam': {'color': 'green', 'faint': True}, 'success': {'bold': True, 'color': 'green'}, 'verbose': {'color': 'blue'}, 'warning': {'color': 'yellow'}}
    level = logging.DEBUG if '-v' in sys.argv or '--verbose' in sys.argv else logging.INFO
    if 1:
        coloredlogs.install(level=level, fmt='%(asctime)s.%(msecs)03d \033[0;90m%(levelname)-8s '
                            ''
                            '\033[0;36m%(filename)-18s%(lineno)3d\033[00m '
                            '%(message)s',
                            level_styles = styles)
    else:
        # Show process name
        coloredlogs.install(level=level, fmt='%(asctime)s.%(msecs)03d \033[0;90m%(levelname)-8s '
                                '\033[0;90m[\033[00m \033[0;35m%(processName)-15s\033[00m\033[0;90m]\033[00m '
                                '\033[0;36m%(filename)s:%(lineno)d\033[00m '
                                '%(message)s')

    logging.info("---[ Starting %s ]---------------------------------------------" % sys.argv[0])
    camera = vapix_control.CameraControl(args.axis_ip, args.axis_username, args.axis_password)
    cameraDelay = args.camera_delay
    cameraMoveSpeed = args.camera_move_speed
    cameraZoom = args.camera_zoom
    cameraConfig = vapix_config.CameraConfiguration(args.axis_ip, args.axis_username, args.axis_password)

    threading.Thread(target = moveCamera, daemon = True).start()
        # Sleep for a bit so we're not hammering the HAT with updates
    time.sleep(0.005)
    flight_topic=args.mqtt_flight_topic
    object_topic = args.mqtt_object_topic
    print("connecting to MQTT broker at "+ args.mqtt_host+", channel '"+flight_topic+"'")
    client = mqtt.Client("skyscan-axis-ptz-camera-" + ID) #create new instance

    client.on_message=on_message #attach function to callback

    client.connect(args.mqtt_host) #connect to broker
    client.loop_start() #start the loop
    client.subscribe(flight_topic)
    client.subscribe(object_topic)
    client.subscribe(config_topic)
    client.publish("skyscan/registration", "skyscan-axis-ptz-camera-"+ID+" Registration", 0, False)

    #############################################
    ##                Main Loop                ##
    #############################################
    timeHeartbeat = 0
    while True:
        if timeHeartbeat < time.mktime(time.gmtime()):
            timeHeartbeat = time.mktime(time.gmtime()) + 10
            client.publish("skyscan/heartbeat", "skyscan-axis-ptz-camera-"+ID+" Heartbeat", 0, False)
        time.sleep(0.1)



if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(e, exc_info=True)
