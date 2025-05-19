import socket
import pickle
import time
import threading
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import sqlite3
from datetime import datetime
import cv2

# === GPIO PINS ===
SERVO_PIN = 18
IR_SENSOR_PIN = 17

# === RFID CONFIG ===
AUTHORIZED_TAGS = {
    771479478350: {"owner": "Aditya", "vehicle": "MH12AB1234"},
    123456789012: {"owner": "Ravi Kumar", "vehicle": "MH14XY5678"},
    987654321098: {"owner": "Sneha Joshi", "vehicle": "MH01JK4321"},
    # Add more RFID entries here
}

# === NETWORK CONFIG ===
SERVER_IP = "192.168.233.184"
SERVER_PORT = 5000

# === CAMERA CLIENT CONFIG ===
CAMERA_SERVER_IP = "192.168.233.147"
CAMERA_SERVER_PORT = 5000
CAMERA_SERVER_PORT2 = 5001  # New second port for streaming


# === SETUP GPIO ===
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(SERVO_PIN, GPIO.OUT)
GPIO.setup(IR_SENSOR_PIN, GPIO.IN)

# === SETUP PWM for SERVO ===
pwm = GPIO.PWM(SERVO_PIN, 50)  # 50Hz
pwm.start(0)

# === SETUP RFID ===
reader = SimpleMFRC522()

# === THREAD LOCK ===
servo_lock = threading.Lock()

# === Track Current Servo Position ===
servo_position = 0  # 0 = 0°, 1 = 90°
last_network_request_time = 0  # Timestamp of last network activation
client_address_global = None  # To store client address for callback
s_global = None  # Global socket reference for callback


def log_rfid_entry(rfid_id, owner, vehicle):
    """
    Log RFID access to the database with timestamp, tag ID, owner name, and vehicle number.
    """
    try:
        conn = sqlite3.connect("access_log.db")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfid_id TEXT,
                owner_name TEXT,
                vehicle_number TEXT,
                access_time TEXT
            )
        """)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO access_log (rfid_id, owner_name, vehicle_number, access_time)
            VALUES (?, ?, ?, ?)
        """, (str(rfid_id), owner, vehicle, timestamp))
        conn.commit()
        conn.close()
        print(f"Logged entry: RFID={rfid_id}, Owner={owner}, Vehicle={vehicle}, Time={timestamp}")
    except Exception as e:
        print(f"Database logging error: {e}")


def set_servo_angle(angle):
    global servo_position
    with servo_lock:
        duty = angle / 18 + 2
        GPIO.output(SERVO_PIN, True)
        pwm.ChangeDutyCycle(duty)
        time.sleep(0.5)
        GPIO.output(SERVO_PIN, False)
        pwm.ChangeDutyCycle(0)
        servo_position = 1 if angle == 90 else 0

        if servo_position == 1:
            print("Gate open")
        else:
            print("Gate closed")


def activate_servo():
    global last_network_request_time
    set_servo_angle(90)
    last_network_request_time = time.time()
    time.sleep(10)
    if servo_position == 1:
        set_servo_angle(0)


def rfid_listener():
    print("RFID listener started...")
    try:
        while True:
            id, text = reader.read()
            print(f"RFID Tag ID: {id}")
            if id in AUTHORIZED_TAGS:
                info = AUTHORIZED_TAGS[id]
                print(f"Access Granted for {info['owner']} with vehicle {info['vehicle']}!")
                log_rfid_entry(id, info['owner'], info['vehicle'])
                activate_servo()
            else:
                print("Access Denied - Invalid RFID!")
            time.sleep(2)
    except Exception as e:
        print(f"RFID listener error: {e}")


def network_listener():
    global client_address_global, s_global
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((SERVER_IP, SERVER_PORT))
    s_global = s
    print(f"Network listener started on {SERVER_IP}:{SERVER_PORT}...")
    try:
        while True:
            data, client_address = s.recvfrom(1024)
            received_data = pickle.loads(data)
            user_value = received_data.get("value", 1)
            print(f"Received from {client_address}: {user_value}")

            if user_value == 1:
                client_address_global = client_address
                activate_servo()

            s.sendto(b"Value received successfully", client_address)
    except Exception as e:
        print(f"Network listener error: {e}")
    finally:
        s.close()


def ir_sensor_monitor():
    global servo_position, last_network_request_time, client_address_global, s_global
    print("IR sensor monitor started...")
    try:
        while True:
            obstacle = GPIO.input(IR_SENSOR_PIN) == 1
            if obstacle and servo_position == 1:
                print("Obstacle Detected! Closing gate...")
                set_servo_angle(0)
                if time.time() - last_network_request_time < 10 and client_address_global:
                    s_global.sendto(b"Value received successfully", client_address_global)
                time.sleep(1)
            time.sleep(0.1)
    except Exception as e:
        print(f"IR sensor error: {e}")


def camera_client():
    """
    Send video frames to a server with a fixed IP address.
    This function implements the client.py functionality.
    """
    print(f"Camera client started... Now sending data to server at {CAMERA_SERVER_IP}:{CAMERA_SERVER_PORT}")

    try:

        # Create two UDP sockets
        s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s1.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 10000000)

        s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s2.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 10000000)

        # OpenCV camera capture
        cap = cv2.VideoCapture(0)  # 0 for the default webcam

        if not cap.isOpened():
            print("Error: Could not open webcam.")
            return

        # Set the camera format to MJPEG
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        # Set a standard resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame.")
                break

            # Ensure the frame size is reasonable
            if frame is None or frame.size == 0:
                print("Empty or corrupted frame!")
                continue

            if frame.shape[0] > 65500 or frame.shape[1] > 65500:
                print("Invalid frame size, skipping...")
                continue

            # Encode the image as JPEG with quality optimization
            ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            if ret:
                x_as_bytes = pickle.dumps(buffer)  # Convert buffer to bytes
                s1.sendto(x_as_bytes, (CAMERA_SERVER_IP, CAMERA_SERVER_PORT))
                s2.sendto(x_as_bytes, (CAMERA_SERVER_IP, CAMERA_SERVER_PORT2))

            else:
                print("Error encoding frame.")

    except Exception as e:
        print(f"Camera client error: {e}")
    finally:
        if 'cap' in locals() and cap is not None:
            cap.release()
        if 's1' in locals() and s1 is not None:
            s1.close()
        if 's2' in locals() and s2 is not None:
            s2.close()


def main():
    try:
        t_rfid = threading.Thread(target=rfid_listener, daemon=True)
        t_net = threading.Thread(target=network_listener, daemon=True)
        t_ir = threading.Thread(target=ir_sensor_monitor, daemon=True)
        t_camera = threading.Thread(target=camera_client, daemon=True)

        t_rfid.start()
        t_net.start()
        t_ir.start()
        t_camera.start()  # Start the camera client thread

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Program interrupted by user.")
    finally:
        pwm.stop()
        GPIO.cleanup()


if __name__ == "__main__":
    main()