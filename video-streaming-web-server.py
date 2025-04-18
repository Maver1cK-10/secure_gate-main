#!/usr/bin/python3

import cv2
import socket
import numpy as np
import pickle
import argparse
import threading
import base64
from flask import Flask, render_template
from flask_socketio import SocketIO

# Set up argument parser to accept IP as an argument
parser = argparse.ArgumentParser(description="UDP Video Stream Web Server")
parser.add_argument("ip", nargs="?", default="10.42.0.1", help="IP address of the server to bind")
parser.add_argument("--web-port", type=int, default=8080, help="Web server port")
args = parser.parse_args()

# Flask app setup
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


# Define route for the home page
@app.route('/')
def index():
    return render_template('index.html')


# Function to receive UDP stream and forward to web clients
def receive_video_stream():
    # Set up the UDP socket
    udp_ip = args.ip
    udp_port = 5001
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((udp_ip, udp_port))

    print(f"UDP server started at {udp_ip}:{udp_port}")
    print(f"Web server running at http://localhost:{args.web_port}")

    try:
        while True:
            # Receive data sent by the client
            x = s.recvfrom(100000000)
            client_ip = x[1][0]
            data = x[0]

            try:
                # Deserialize the received byte data into a Numpy array
                data = pickle.loads(data)

                # Decode the Numpy array to an image
                frame = cv2.imdecode(data, cv2.IMREAD_COLOR)

                # Convert frame to JPEG format
                ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])

                # Convert to base64 for sending to web clients
                jpeg_bytes = jpeg.tobytes()
                base64_image = base64.b64encode(jpeg_bytes).decode('utf-8')

                # Emit the frame to all connected web clients
                socketio.emit('video_frame', {'image': f'data:image/jpeg;base64,{base64_image}'})

            except Exception as e:
                print(f"Error processing frame: {e}")
    finally:
        s.close()


# Create the templates directory and index.html file
import os

# Make sure templates directory exists
os.makedirs('templates', exist_ok=True)

# Create the HTML template file
with open('templates/index.html', 'w') as f:
    f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>Video Stream</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background-color: #f0f0f0;
            font-family: Arial, sans-serif;
        }
        .container {
            text-align: center;
        }
        #video-container {
            max-width: 100%;
            border: 1px solid #ccc;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }
        #video-stream {
            max-width: 100%;
            height: auto;
        }
        h1 {
            color: #333;
        }
        .status {
            margin-top: 10px;
            padding: 5px;
            color: #555;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Live Video Stream</h1>
        <div id="video-container">
            <img id="video-stream" src="" alt="Waiting for video stream...">
        </div>
        <div class="status" id="connection-status">Connecting to stream...</div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Connect to Socket.IO server
            const socket = io();
            const videoElement = document.getElementById('video-stream');
            const statusElement = document.getElementById('connection-status');

            // Handle incoming video frames
            socket.on('video_frame', function(data) {
                videoElement.src = data.image;
                statusElement.textContent = 'Connected to stream';
                statusElement.style.color = 'green';
            });

            // Handle connection events
            socket.on('connect', function() {
                statusElement.textContent = 'Connected to server, waiting for video...';
                statusElement.style.color = 'blue';
            });

            socket.on('disconnect', function() {
                statusElement.textContent = 'Disconnected from server';
                statusElement.style.color = 'red';
            });
        });
    </script>
</body>
</html>
    ''')

if __name__ == '__main__':
    # Start the UDP receiver in a separate thread
    receiver_thread = threading.Thread(target=receive_video_stream)
    receiver_thread.daemon = True
    receiver_thread.start()

    # Start the Flask web server
    socketio.run(app, host='0.0.0.0', port=args.web_port, debug=False)