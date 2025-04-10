from flask import Flask, render_template, request
import sqlite3
from datetime import datetime

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html', selected_date='', no_data=False)


@app.route('/checkin', methods=['POST'])
def checkin():
    selected_date = request.form.get('selected_date')
    selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d')
    formatted_date = selected_date_obj.strftime('%Y-%m-%d')

    conn = sqlite3.connect('secure_gate.db')  # Connect to the new database name if required
    cursor = conn.cursor()

    cursor.execute("SELECT name, time FROM secure_gate WHERE date = ?", (formatted_date,))
    entry_data = cursor.fetchall()

    conn.close()

    if not entry_data:
        return render_template('index.html', selected_date=selected_date, no_data=True)

    return render_template('index.html', selected_date=selected_date, entry_data=entry_data)


if __name__ == '__main__':
    app.run(debug=True)
