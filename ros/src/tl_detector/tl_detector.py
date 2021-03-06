#!/usr/bin/env python
import rospy
from std_msgs.msg import Int32, Bool
from geometry_msgs.msg import PoseStamped, Pose
from styx_msgs.msg import TrafficLightArray, TrafficLight
from styx_msgs.msg import Lane
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from light_classification.tl_classifier import TLClassifier
from scipy.spatial import KDTree
import tf
import cv2
import yaml
from time import time

STATE_COUNT_THRESHOLD = 1


class TLDetector(object):
    def __init__(self):

        rospy.init_node('tl_detector')

        self.pose = None
        self.waypoints = None
        self.camera_image = None
        self.lights = []
        self.base_waypoints = None
        self.waypoints_2d = None
        self.waypoint_tree = None
        self.has_image = None
        self.img_filter = 0
        
        self.time_counter = None

        sub1 = rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
        sub2 = rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

        '''
        /vehicle/traffic_lights provides you with the location of the traffic light in 3D map space and
        helps you acquire an accurate ground truth data source for the traffic light
        classifier by sending the current color state of all traffic lights in the
        simulator. When testing on the vehicle, the color state will not be available. You'll need to
        rely on the position of the light and the camera image to predict it.
        '''
        self.tl_detector_init = rospy.Publisher('/tl_detector_initialized', Bool, queue_size=1)
        self.init_done = False

        sub3 = rospy.Subscriber('/vehicle/traffic_lights', TrafficLightArray, self.traffic_cb)
        sub6 = rospy.Subscriber('/image_color', Image, self.image_cb)

        config_string = rospy.get_param("/traffic_light_config")
        self.config = yaml.load(config_string)

        
        self.upcoming_red_light_pub = rospy.Publisher('/traffic_waypoint', Int32, queue_size=1)
        #self.tl_detector_init.publish(Bool(False))

        self.bridge = CvBridge()
        self.light_classifier = TLClassifier()
        self.tl_detector_init.publish(Bool(True))
        self.init_done = True
        self.listener = tf.TransformListener()

        self.state = TrafficLight.UNKNOWN
        self.last_state = TrafficLight.UNKNOWN
        self.last_wp = -1
        self.state_count = 0

        rospy.spin()

    def pose_cb(self, msg):
        self.pose = msg

    def waypoints_cb(self, waypoints):
        self.base_waypoints = waypoints
        if not self.waypoints_2d:
            self.waypoints_2d = [[waypoint.pose.pose.position.x, waypoint.pose.pose.position.y] for waypoint in
                                 waypoints.waypoints]
            self.waypoint_tree = KDTree(self.waypoints_2d)

    def traffic_cb(self, msg):
        self.lights = msg.lights

    def image_cb(self, msg):

        """Identifies red lights in the incoming camera image and publishes the index
            of the waypoint closest to the red light's stop line to /traffic_waypoint
        Args:
            msg (Image): image from car-mounted camera
        """

        if self.init_done:

            self.has_image = True
            self.camera_image = msg

            
            light_wp, state = self.process_traffic_lights()

            # new logic
            # if state changed we need to determine the change, relevant for publishing is only red and yellow lights
            if self.state != state:
                self.state_count = 0
                self.state = state
		rospy.loginfo('Mode: Free Drive.')
            elif self.state_count >= STATE_COUNT_THRESHOLD and (state == TrafficLight.RED or state == TrafficLight.YELLOW):
                self.last_wp = light_wp
                self.upcoming_red_light_pub.publish(Int32(light_wp))
		rospy.loginfo('Mode: Stoping at red light.')
            elif (state == TrafficLight.GREEN or state == TrafficLight.UNKNOWN):
                self.last_wp = -1
                self.upcoming_red_light_pub.publish(Int32(self.last_wp))
		rospy.loginfo('Mode: Free Drive.')
            else:
                self.upcoming_red_light_pub.publish(Int32(self.last_wp))
		rospy.loginfo('Mode: Free Drive.')
                self.state_count += 1



    def get_closest_waypoint(self, x, y):

        closest_idx = self.waypoint_tree.query([x, y], 1)[1]
        return closest_idx

    def get_light_state(self, light):

        if (not self.has_image):
            self.prev_light_loc = None
        cv_image = self.bridge.imgmsg_to_cv2(self.camera_image, "bgr8")
        pred_color = self.light_classifier.get_classification(cv_image)

        #rospy.loginfo('True Color: {}'.format(light.state))
        #rospy.loginfo('Pred Color: {}'.format(pred_color))

        return pred_color

    def process_traffic_lights(self):
        
        """Finds closest visible traffic light, if one exists, and determines its
            location and color
        Returns:
            int: index of waypoint closes to the upcoming stop line for a traffic light (-1 if none exists)
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)
        """

        closest_light = None
        line_wp_idx = None

        # List of positions that correspond to the line to stop in front of for a given intersection
        stop_line_positions = self.config['stop_line_positions']

        if self.pose:
            car_wp_idx = self.get_closest_waypoint(self.pose.pose.position.x, self.pose.pose.position.y)

            diff = len(self.base_waypoints.waypoints)
            for i, light in enumerate(self.lights):
                # Get stop line waypoint index
                line = stop_line_positions[i]
                temp_wp_idx = self.get_closest_waypoint(line[0], line[1])
                # Find closest stop line waypoint index
                d = temp_wp_idx - car_wp_idx
                if 0 <= d < diff:
                    diff = d
                    closest_light = light
                    line_wp_idx = temp_wp_idx

        # implemented distance check to skip image processing
        # maybe turn of in site test

        if closest_light and diff < 150:
            state = self.get_light_state(closest_light)
            return line_wp_idx, state

        return -1, TrafficLight.UNKNOWN


if __name__ == '__main__':
    try:
        TLDetector()
    except rospy.ROSInterruptException:
        rospy.logerr('Could not start traffic node.')
