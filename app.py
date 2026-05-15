from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

CARSXE_API_KEY = os.environ.get('CARSXE_API_KEY', '')
NHTSA_BASE = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin'
CARSXE_BASE = 'https://api.carsxe.com'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/vin', methods=['GET'])
def decode_vin():
    vin = request.args.get('vin', '').strip().upper()
    
    if not vin or len(vin) != 17:
        return jsonify({'error': 'Invalid VIN. Must be exactly 17 characters.'}), 400

    result = {}

    # Step 1: NHTSA free API - basic car info
    try:
        nhtsa_url = f"{NHTSA_BASE}/{vin}?format=json"
        nhtsa_res = requests.get(nhtsa_url, timeout=10)
        nhtsa_data = nhtsa_res.json()
        
        variables = {}
        for item in nhtsa_data.get('Results', []):
            if item.get('Value') and item['Value'] not in ['', 'Not Applicable', '0']:
                variables[item['Variable']] = item['Value']
        
        result['make'] = variables.get('Make', 'Unknown')
        result['model'] = variables.get('Model', 'Unknown')
        result['year'] = variables.get('Model Year', 'Unknown')
        result['body'] = variables.get('Body Class', 'Unknown')
        result['engine'] = variables.get('Displacement (L)', '')
        result['cylinders'] = variables.get('Engine Number of Cylinders', '')
        result['fuel'] = variables.get('Fuel Type - Primary', 'Unknown')
        result['plant_country'] = variables.get('Plant Country', 'Unknown')
        result['vehicle_type'] = variables.get('Vehicle Type', 'Unknown')
        result['trim'] = variables.get('Trim', '')
        result['drive'] = variables.get('Drive Type', '')
        result['transmission'] = variables.get('Transmission Style', '')
        result['doors'] = variables.get('Number of Doors', '')
        result['seats'] = variables.get('Number of Seat Rows', '')
        
        # Build engine string
        engine_str = ''
        if result['engine']:
            engine_str += f"{result['engine']}L"
        if result['cylinders']:
            engine_str += f" {result['cylinders']}-Cylinder"
        if result['fuel']:
            engine_str += f" {result['fuel']}"
        result['engine_display'] = engine_str if engine_str else 'Not Available'
        
        # Build title
        result['title'] = f"{result['year']} {result['make']} {result['model']}"
        if result['trim']:
            result['title'] += f" {result['trim']}"
        
    except Exception as e:
        return jsonify({'error': f'NHTSA API error: {str(e)}'}), 500

    # Step 2: CarsXE API - specs + history (if key available)
    if CARSXE_API_KEY:
        try:
            # Specs
            specs_url = f"{CARSXE_BASE}/specs?key={CARSXE_API_KEY}&vin={vin}"
            specs_res = requests.get(specs_url, timeout=10)
            if specs_res.status_code == 200:
                specs = specs_res.json()
                result['specs'] = specs
                result['has_specs'] = True
            else:
                result['has_specs'] = False
        except:
            result['has_specs'] = False

        try:
            # History
            history_url = f"{CARSXE_BASE}/history?key={CARSXE_API_KEY}&vin={vin}"
            history_res = requests.get(history_url, timeout=10)
            if history_res.status_code == 200:
                history = history_res.json()
                result['history'] = history
                result['has_history'] = True
                # Count records
                records = 0
                if isinstance(history, dict):
                    for key in history:
                        if isinstance(history[key], list):
                            records += len(history[key])
                result['records_count'] = records if records > 0 else 'Multiple'
            else:
                result['has_history'] = False
                result['records_count'] = 0
        except:
            result['has_history'] = False
            result['records_count'] = 0
    else:
        result['has_specs'] = False
        result['has_history'] = False
        result['records_count'] = 'Multiple'

    result['vin'] = vin
    result['success'] = True

    return jsonify(result)

@app.route('/api/recalls', methods=['GET'])
def get_recalls():
    vin = request.args.get('vin', '').strip().upper()
    if not vin:
        return jsonify({'error': 'VIN required'}), 400
    try:
        url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?vin={vin}"
        res = requests.get(url, timeout=10)
        data = res.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
