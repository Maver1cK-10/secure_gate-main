import dlib
import numpy as np
import cv2
import os
import pandas as pd
import time
import logging
import sqlite3
import datetime
import socket
import pickle

# Dlib / Use frontal face detector of Dlib
detector = dlib.get_frontal_face_detector()

# Dlib landmark / Get face landmarks
predictor = dlib.shape_predictor('data/data_dlib/shape_predictor_68_face_landmarks.dat')

# Dlib Resnet Use Dlib resnet50 model to get 128D face descriptor
face_reco_model = dlib.face_recognition_model_v1("data/data_dlib/dlib_face_recognition_resnet_model_v1.dat")

# Create a connection to the database
conn = sqlite3.connect("secure_gate.db")
cursor = conn.cursor()

# Create a table for the entry book
table_name = "secure_gate"
create_table_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (name TEXT, time TEXT, date DATE, UNIQUE(time, date))"
cursor.execute(create_table_sql)

# Commit changes and close the connection
conn.commit()
conn.close()

# Define server details for sending data
server_ip = "192.168.233.184"
server_port = 5000

def send_data_to_server(age, server_ip, server_port):
    """
    Sends the user's age data to the server.
    """
    print(f"Sending data to the server...{server_ip}")

    # Create UDP socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Prepare data to send
    send_data = {'age': age}
    x_as_bytes = pickle.dumps(send_data)

    # Send data to the server
    s.sendto(x_as_bytes, (server_ip, server_port))

    # Wait for server response
    response, _ = s.recvfrom(1024)
    print(f"Server Response: {response.decode()}")

class RemoteVideoStream:
    def __init__(self, server_ip='192.168.233.147', port=5000):
        self.server_ip = server_ip
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((server_ip, port))
        self.current_frame = None

    def read(self):
        try:
            # Receive data from the network
            x = self.socket.recvfrom(100000000)
            data = pickle.loads(x[0])

            # Decode the frame
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            self.current_frame = frame
            return True, frame
        except Exception as e:
            print(f"Error receiving frame: {e}")
            return False, None

    def isOpened(self):
        return True  # Always consider the stream as open

class Face_Recognizer:

    def send_door_command(self, command):
        try:
            command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            command_socket.sendto(command.encode(), (self.server_ip, 5001))
            print(f"Sent command: {command}")
        except Exception as e:
            print(f"Failed to send command: {e}")

    def __init__(self, pi_ip='192.168.233.147'):

        # def _init_(self, pi_ip='192.168.69.147'):  # Add parameter
        self.server_ip = pi_ip  # Store Pi's IP

            # Rest of existing initialization...
        self.font = cv2.FONT_ITALIC

        # FPS
        self.frame_time = 0
        self.frame_start_time = 0
        self.fps = 0
        self.fps_show = 0
        self.start_time = time.time()

        # cnt for frame
        self.frame_cnt = 0

        # Save the features of faces in the database
        self.face_features_known_list = []
        # Save the name of faces in the database
        self.face_name_known_list = []

        # List to save centroid positions of ROI in frame N-1 and N
        self.last_frame_face_centroid_list = []
        self.current_frame_face_centroid_list = []

        # List to save names of objects in frame N-1 and N
        self.last_frame_face_name_list = []
        self.current_frame_face_name_list = []

        # cnt for faces in frame N-1 and N
        self.last_frame_face_cnt = 0
        self.current_frame_face_cnt = 0

        # Save the e-distance for faceX when recognizing
        self.current_frame_face_X_e_distance_list = []

        # Save the positions and names of current faces captured
        self.current_frame_face_position_list = []
        # Save the features of people in current frame
        self.current_frame_face_feature_list = []

        # e distance between centroid of ROI in last and current frame
        self.last_current_frame_centroid_e_distance = 0

        # Reclassify after 'reclassify_interval' frames
        self.reclassify_interval_cnt = 0
        self.reclassify_interval = 10



    # Rest of the methods remain exactly the same as in the original entry_taker.py

    # "features_all.csv" / Get known faces from "features_all.csv"
    def get_face_database(self):
        if os.path.exists("data/features_all.csv"):
            path_features_known_csv = "data/features_all.csv"
            csv_rd = pd.read_csv(path_features_known_csv, header=None)
            for i in range(csv_rd.shape[0]):
                features_someone_arr = []
                self.face_name_known_list.append(csv_rd.iloc[i][0])
                for j in range(1, 129):
                    if csv_rd.iloc[i][j] == '':
                        features_someone_arr.append('0')
                    else:
                        features_someone_arr.append(csv_rd.iloc[i][j])
                self.face_features_known_list.append(features_someone_arr)
            logging.info("Faces in Database： %d", len(self.face_features_known_list))
            return 1
        else:
            logging.warning("'features_all.csv' not found!")
            logging.warning("Please run 'get_faces_from_camera.py' "
                            "and 'features_extraction_to_csv.py' before 'face_reco_from_camera.py'")
            return 0

    def update_fps(self):
        now = time.time()
        # Refresh fps per second
        if str(self.start_time).split(".")[0] != str(now).split(".")[0]:
            self.fps_show = self.fps
        self.start_time = now
        self.frame_time = now - self.frame_start_time
        self.fps = 1.0 / self.frame_time
        self.frame_start_time = now

    @staticmethod
    # Compute the e-distance between two 128D features
    def return_euclidean_distance(feature_1, feature_2):
        feature_1 = np.array(feature_1)
        feature_2 = np.array(feature_2)
        dist = np.sqrt(np.sum(np.square(feature_1 - feature_2)))
        return dist

    # Use centroid tracker to link face_x in current frame with person_x in last frame
    def centroid_tracker(self):
        for i in range(len(self.current_frame_face_centroid_list)):
            e_distance_current_frame_person_x_list = []
            # For object 1 in current_frame, compute e-distance with object 1/2/3/4/... in last frame
            for j in range(len(self.last_frame_face_centroid_list)):
                self.last_current_frame_centroid_e_distance = self.return_euclidean_distance(
                    self.current_frame_face_centroid_list[i], self.last_frame_face_centroid_list[j])

                e_distance_current_frame_person_x_list.append(
                    self.last_current_frame_centroid_e_distance)

            last_frame_num = e_distance_current_frame_person_x_list.index(
                min(e_distance_current_frame_person_x_list))
            self.current_frame_face_name_list[i] = self.last_frame_face_name_list[last_frame_num]

    # cv2 window / putText on cv2 window
    def draw_note(self, img_rd):
        # Add some info on windows
        cv2.putText(img_rd, "Face Recognizer with Deep Learning", (20, 40), self.font, 1, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(img_rd, "Frame:  " + str(self.frame_cnt), (20, 100), self.font, 0.8, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(img_rd, "FPS:    " + str(self.fps.__round__(2)), (20, 130), self.font, 0.8, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(img_rd, "Faces:  " + str(self.current_frame_face_cnt), (20, 160), self.font, 0.8, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(img_rd, "Q: Quit", (20, 450), self.font, 0.8, (255, 255, 255), 1, cv2.LINE_AA)

    # insert data in database for entry log
    def entry_log(self, name):
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect("secure_gate.db")
        cursor = conn.cursor()
        # Check if the resident's entry has already been recorded for the current date
        cursor.execute("SELECT * FROM secure_gate WHERE name = ? AND date = ?", (name, current_date))
        existing_entry = cursor.fetchone()

        current_time = datetime.datetime.now().strftime('%H:%M:%S')
        cursor.execute("INSERT INTO secure_gate (name, time, date) VALUES (?, ?, ?)",
                       (name, current_time, current_date))
        conn.commit()
        print(f"{name}'s entry logged in entry book at {current_time} on {current_date}")

        conn.close()

    # Process function modified to handle society entry control
    def process(self, stream):
        # 1. Get faces known from "features_all.csv"
        if self.get_face_database():
            while stream.isOpened():
                self.frame_cnt += 1
                logging.debug("Frame " + str(self.frame_cnt) + " starts")
                flag, img_rd = stream.read()

                if not flag:
                    print("Failed to grab frame from stream")
                    break

                kk = cv2.waitKey(1)

                # 2. Detect faces for frame X
                faces = detector(img_rd, 0)

                # 3. Update cnt for faces in frames
                self.last_frame_face_cnt = self.current_frame_face_cnt
                self.current_frame_face_cnt = len(faces)

                # 4. Update the face name list in last frame
                self.last_frame_face_name_list = self.current_frame_face_name_list[:]

                # 5. Update frame centroid list
                self.last_frame_face_centroid_list = self.current_frame_face_centroid_list
                self.current_frame_face_centroid_list = []

                if (self.current_frame_face_cnt == self.last_frame_face_cnt) and (
                        self.reclassify_interval_cnt != self.reclassify_interval):
                    self.current_frame_face_position_list = []

                    if "unknown" in self.current_frame_face_name_list:
                        self.reclassify_interval_cnt += 1

                    if self.current_frame_face_cnt != 0:
                        for k, d in enumerate(faces):
                            self.current_frame_face_position_list.append(tuple(
                                [faces[k].left(), int(faces[k].bottom() + (faces[k].bottom() - faces[k].top()) / 4)]))
                            self.current_frame_face_centroid_list.append(
                                [int(faces[k].left() + faces[k].right()) / 2,
                                 int(faces[k].top() + faces[k].bottom()) / 2])

                            img_rd = cv2.rectangle(img_rd,
                                                   tuple([d.left(), d.top()]),
                                                   tuple([d.right(), d.bottom()]),
                                                   (255, 255, 255), 2)

                    if self.current_frame_face_cnt != 1:
                        self.centroid_tracker()

                    for i in range(self.current_frame_face_cnt):
                        img_rd = cv2.putText(img_rd, self.current_frame_face_name_list[i],
                                             self.current_frame_face_position_list[i], self.font, 0.8, (0, 255, 255), 1,
                                             cv2.LINE_AA)
                    self.draw_note(img_rd)

                else:
                    self.current_frame_face_position_list = []
                    self.current_frame_face_X_e_distance_list = []
                    self.current_frame_face_feature_list = []
                    self.reclassify_interval_cnt = 0

                    if self.current_frame_face_cnt == 0:
                        self.current_frame_face_name_list = []
                    else:
                        self.current_frame_face_name_list = []
                        for i in range(len(faces)):
                            shape = predictor(img_rd, faces[i])
                            self.current_frame_face_feature_list.append(
                                face_reco_model.compute_face_descriptor(img_rd, shape))
                            self.current_frame_face_name_list.append("unknown")

                        for k in range(len(faces)):
                            self.current_frame_face_centroid_list.append(
                                [int(faces[k].left() + faces[k].right()) / 2,
                                 int(faces[k].top() + faces[k].bottom()) / 2])

                            self.current_frame_face_X_e_distance_list = []
                            self.current_frame_face_position_list.append(tuple(
                                [faces[k].left(), int(faces[k].bottom() + (faces[k].bottom() - faces[k].top()) / 4)]))

                            for i in range(len(self.face_features_known_list)):
                                if str(self.face_features_known_list[i][0]) != '0.0':
                                    e_distance_tmp = self.return_euclidean_distance(
                                        self.current_frame_face_feature_list[k],
                                        self.face_features_known_list[i])
                                    self.current_frame_face_X_e_distance_list.append(e_distance_tmp)
                                else:
                                    self.current_frame_face_X_e_distance_list.append(999999999)

                            similar_person_num = self.current_frame_face_X_e_distance_list.index(
                                min(self.current_frame_face_X_e_distance_list))

                            # Modify the recognition block (~line 290):
                            if min(self.current_frame_face_X_e_distance_list) < 0.4:
                                name = self.face_name_known_list[similar_person_num]
                                self.entry_log(name)
                                # self.send_door_command("OPEN_DOOR")  # Send open command
                                send_data_to_server(1, server_ip, server_port)
                                print(f"Access granted for {name}")

                                # cv2.waitKey(5000)  # Keep message visible
                            else:
                                print("Access Denied: Unknown person")
                                # cv2.waitKey(2000)  # Shorter delay for denied access

                        self.draw_note(img_rd)

                if kk == ord('q'):
                    break

                self.update_fps()
                cv2.namedWindow("camera", 1)
                cv2.imshow("camera", img_rd)

                logging.debug("Frame ends\n\n")

    def run(self, server_ip='192.168.233.147'):
        # Create RemoteVideoStream instead of using local camera
        video_stream = RemoteVideoStream(server_ip)
        self.process(video_stream)

        cv2.destroyAllWindows()

def main():
    # logging.basicConfig(level=logging.DEBUG) # Set log level to 'logging.DEBUG' to print debug info of every frame
    logging.basicConfig(level=logging.INFO)
    Face_Recognizer_con = Face_Recognizer()

    # Optional: Pass server IP if different from default
    # Face_Recognizer_con.run('10.42.0.154')
    Face_Recognizer_con.run()

if __name__ == '__main__':
    main()