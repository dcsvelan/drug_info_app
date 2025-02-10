# app.py
from flask import Flask, request, jsonify, render_template, send_file
import requests
import pyttsx3
import random
from openpyxl import Workbook
from io import BytesIO
import os
import json
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Ensure cache folder exists
CACHE_FOLDER = os.path.join(os.getcwd(), "cache")
if not os.path.exists(CACHE_FOLDER):
    os.makedirs(CACHE_FOLDER)

# Sample messages for the homepage
messages = [
    "Did you know? The FDA ensures drug labels are clear.",
    "Stay informed with FDA drug label details!",
    "Your drug label information is just a query away."
]

# Utility: Generate a safe cache file path for a drug name
def get_cache_path(drug_name):
    safe_name = "".join(c for c in drug_name if c.isalnum() or c in (' ', '_')).rstrip()
    return os.path.join(CACHE_FOLDER, f"{safe_name.lower()}.json")

@app.route('/')
def index():
    selected_message = random.choice(messages)
    return render_template('index.html', message=selected_message)

@app.route('/get_drug_label', methods=['POST'])
def get_drug_label():
    drug_name = request.json.get('drug_name')
    if not drug_name:
        return jsonify({'error': 'No drug name provided'}), 400

    cache_file = get_cache_path(drug_name)
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            cached_data = json.load(f)
        return jsonify(cached_data)

    url = f'https://api.fda.gov/drug/label.json?search=openfda.brand_name:"{drug_name}"&limit=1'
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch data from the FDA API'}), 500

    data = response.json()
    with open(cache_file, 'w') as f:
        json.dump(data, f)
    return jsonify(data)

@app.route('/speak', methods=['POST'])
def speak():
    text = request.json.get('text')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
    return jsonify({'status': 'success'})

@app.route('/download_results', methods=['POST'])
def download_results():
    drug_name = request.json.get('drug_name')
    if not drug_name:
        return jsonify({'error': 'No drug name provided'}), 400

    cache_file = get_cache_path(drug_name)
    if not os.path.exists(cache_file):
        return jsonify({'error': 'Drug label data not found in cache'}), 404

    with open(cache_file, 'r') as f:
        drug_data = json.load(f)

    wb = Workbook()
    ws = wb.active
    ws.append(['Field', 'Value'])
    results = drug_data.get('results', [{}])
    if results:
        for key, value in results[0].items():
            ws.append([key, str(value)])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(buffer, attachment_filename=f'{drug_name}_drug_label.xlsx', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
