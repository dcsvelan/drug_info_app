from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for, flash
import requests
import os
import json
from dotenv import load_dotenv
from openpyxl import Workbook
from io import BytesIO
import concurrent.futures
from functools import wraps
import pyttsx3
import random
import asyncio
from cachetools import TTLCache, LRUCache
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def greet_json():
    return {"Hello": "World!"}



# Import authentication module
from auth import db, bcrypt, User, login_required

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")

# Database configuration
db_folder = os.path.join(os.getcwd(), "database")
if not os.path.exists(db_folder):
    os.makedirs(db_folder)

db_file = os.path.join(db_folder, "db.sqlite3")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_file}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions with app
db.init_app(app)
bcrypt.init_app(app)

# Authentication routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose another.', 'danger')
            return redirect(url_for('register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ---------------------------
# Mapping and Global Variables
# ---------------------------
class_type_mapping = {
    "ci_with": "Contraindications",
    "ci_moa": "Contraindications (MoA)",
    "ci_pe": "Contraindications (Effects)",
    "ci_chemclass": "Contraindications (Chem)",
    "has_pe": "Effects",
    "has_moa": "MoA",
    "has_epc": "Drug Class",
    "may_treat": "To Treat"
}

ordered_class_types = [
    "ci_with", "ci_moa", "ci_pe", "ci_chemclass", "has_pe", "has_moa", "has_epc", "may_treat"
]

jokes = [
    "Aristotle: To actualize its potential.",
    "Plato: For the greater good.",
    "Socrates: To examine the other side.",
    "Descartes: It had sufficient reason to believe it was dreaming.",
    "Hume: Out of habit.",
    "Kant: Out of a sense of duty.",
    "Nietzsche: Because if you gaze too long across the road, the road gazes also across you.",
    "Hegel: To fulfill the dialectical progression.",
    "Marx: It was a historical inevitability.",
    "Sartre: In order to act in good faith and be true to itself.",
    "Camus: One must imagine Sisyphus happy and the chicken crossing the road.",
    "Wittgenstein: The meaning of 'cross' was in the use, not in the action.",
    "Derrida: The chicken was making a deconstructive statement on the binary opposition of 'this side' and 'that side.'",
    "Heidegger: To authentically dwell in the world.",
    "Foucault: Because of the societal structures and power dynamics at play.",
    "Chomsky: For a syntactic, not pragmatic, purpose.",
    "Buddha: If you meet the chicken on the road, kill it.",
    "Laozi: The chicken follows its path naturally.",
    "Confucius: The chicken crossed the road to reach the state of Ren.",
    "Leibniz: In the best of all possible worlds, the chicken would cross the road."
]

# In-memory caches for RxNav and FDA data
rxnav_cache = {}
fda_cache = {}

# ---------------------------
# Utility Functions for Caching
# ---------------------------
CACHE_FOLDER = os.path.join(os.getcwd(), "cache")
if not os.path.exists(CACHE_FOLDER):
    os.makedirs(CACHE_FOLDER)

def get_safe_name(drug_name):
    return "".join(c for c in drug_name if c.isalnum() or c in (' ', '_')).rstrip().lower()

def get_rxnav_cache_path(drug_name):
    safe_name = get_safe_name(drug_name)
    return os.path.join(CACHE_FOLDER, f"{safe_name}_rxnav.json")

def get_fda_cache_path(drug_name):
    safe_name = get_safe_name(drug_name)
    return os.path.join(CACHE_FOLDER, f"{safe_name}_fda.json")
# ---------------------------
# Drug Data Fetching
# ---------------------------
def fetch_rxnav_data(drug_name):
    """Fetch RxNav drug class information and update cache."""
    if drug_name in rxnav_cache:
        return rxnav_cache[drug_name]
    rxnav_path = get_rxnav_cache_path(drug_name)
    if os.path.exists(rxnav_path):
        with open(rxnav_path, 'r') as f:
            rxnav_data = json.load(f)
    else:
        class_types = {rela: set() for rela in ordered_class_types}
        for rela in ordered_class_types:
            url = f"https://rxnav.nlm.nih.gov/REST/rxclass/class/byDrugName.json?drugName={drug_name}&relaSource=ALL&relas={rela}"
            response = requests.get(url)
            if response.status_code != 200:
                return {'error': 'Failed to fetch data from USFDA'}
            data = response.json()
            if 'rxclassDrugInfoList' in data:
                drug_classes = data['rxclassDrugInfoList'].get('rxclassDrugInfo', [])
                for cls in drug_classes:
                    class_name = cls['rxclassMinConceptItem']['className']
                    class_types[rela].add(class_name)
        mapped_classes = {class_type_mapping[rela]: list(class_types[rela]) for rela in ordered_class_types}
        rxnav_data = {'drug_name': drug_name, 'classes': mapped_classes}
        with open(rxnav_path, 'w') as f:
            json.dump(rxnav_data, f)
    rxnav_cache[drug_name] = rxnav_data
    return rxnav_data

def fetch_fda_data(drug_name):
    """Fetch FDA drug label information and update cache."""
    if drug_name in fda_cache:
        return fda_cache[drug_name]
    fda_path = get_fda_cache_path(drug_name)
    if os.path.exists(fda_path):
        with open(fda_path, 'r') as f:
            fda_data = json.load(f)
    else:
        url = f'https://api.fda.gov/drug/label.json?search=openfda.brand_name:"{drug_name}"&limit=1'
        response = requests.get(url)
        if response.status_code != 200:
            return {'error': 'Failed to fetch data from the USFDA'}
        fda_data = response.json()
        with open(fda_path, 'w') as f:
            json.dump(fda_data, f)
    fda_cache[drug_name] = fda_data
    return fda_data

# Main application routes
@app.route('/')
@login_required
def index():
    selected_joke = random.choice(jokes)
    return render_template('index.html', quote=selected_joke)

@app.route('/get_drug_info', methods=['POST'])
def get_drug_info():
    drug_name = request.json.get('drug_name')
    if not drug_name:
        return jsonify({'error': 'No drug name provided'}), 400

    # Use ThreadPoolExecutor to fetch RxNav and FDA data concurrently.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_rxnav = executor.submit(fetch_rxnav_data, drug_name)
        future_fda = executor.submit(fetch_fda_data, drug_name)
        rxnav_data = future_rxnav.result()
        fda_data = future_fda.result()

    # Check if either call returned an error:
    if 'error' in rxnav_data:
        return jsonify(rxnav_data), 500
    if 'error' in fda_data:
        return jsonify(fda_data), 500

    # Merge "ask_doctor_or_pharmacist" into "ask_doctor" if both exist in FDA data.
    if fda_data.get('results') and fda_data['results'][0].get("ask_doctor") and fda_data['results'][0].get("ask_doctor_or_pharmacist"):
        doc_val = fda_data['results'][0]["ask_doctor"]
        pharm_val = fda_data['results'][0]["ask_doctor_or_pharmacist"]
        if isinstance(doc_val, list):
            doc_val = ", ".join(doc_val)
        if isinstance(pharm_val, list):
            pharm_val = ", ".join(pharm_val)
        fda_data['results'][0]["ask_doctor"] = doc_val + " " + pharm_val
        del fda_data['results'][0]["ask_doctor_or_pharmacist"]

    # Update the joke when Find is pressed
    updated_joke = random.choice(jokes)
    combined = {
        "drug_name": drug_name,
        "rxnav": rxnav_data,
        "fda": fda_data,
        "quote": updated_joke
    }
    return jsonify(combined)

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
@login_required
def download_results():
    drug_name = request.json.get('drug_name')
    if not drug_name:
        return jsonify({'error': 'No drug name provided'}), 400

    # Fetch data before generating report
    rxnav_data = fetch_rxnav_data(drug_name)
    fda_data = fetch_fda_data(drug_name)

    # Create Excel file
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "RxNav Data"
    ws1.append(['Class Type', 'Classes'])
    
    for class_type, classes in rxnav_data.get('classes', {}).items():
        ws1.append([class_type, ', '.join(classes)])
    
    ws2 = wb.create_sheet(title="FDA Data")
    ws2.append(['Field', 'Value'])
    
    for key, value in fda_data.items():
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        ws2.append([key, str(value)])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f'{drug_name}_drug_info.xlsx')

# Create database tables
def init_db():
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)