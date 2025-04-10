from flask import Flask, render_template, request, jsonify
import subprocess
import os
import signal

app = Flask(__name__)

# Store process references
processes = {}

# Function to start a script
def start_script(script_name):
    if script_name in processes:
        return f"{script_name} is already running."
    process = subprocess.Popen(["python", script_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    processes[script_name] = process
    return f"Started {script_name}"

# Function to stop a script
def stop_script(script_name):
    if script_name in processes:
        process = processes.pop(script_name)
        os.kill(process.pid, signal.SIGTERM)
        return f"Stopped {script_name}"
    return f"{script_name} is not running."

@app.route("/")
def home():
    return render_template("demo.html")

@app.route("/run", methods=["POST"])
def run_script():
    script_name = request.form["script"]
    return jsonify({"message": start_script(script_name)})

@app.route("/stop", methods=["POST"])
def stop_script():
    script_name = request.form["script"]
    return jsonify({"message": stop_script(script_name)})

if __name__ == "__main__":
    app.run(debug=True)
