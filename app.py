from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import os

app = Flask(__name__)

# 🔒 Secret Key
SECRET_KEY = "Akshay12apidev"

def run_playwright_flow(number, otp=None):
    # हर रिक्वेस्ट पर नया ब्राउज़र लॉन्च करें (क्रैश से बचने के लिए)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        # ⚡ स्पीड बूस्टर: इमेज, फॉन्ट, CSS ब्लॉक करें (सिर्फ HTML लोड होगा)
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_())
        
        page = context.new_page()
        
        try:
            # 1. पेज पर जाएं (10 सेकंड का टाइमआउट)
            page.goto("https://m.krsnaarpl.com/validate-login.html", timeout=10000)
            
            # 2. मोबाइल नंबर भरें (3 सेकंड का टाइमआउट)
            page.fill('input[placeholder="Enter mobile No."]', number, timeout=3000)
            
            # 3. Get OTP बटन पर क्लिक करें
            page.click('text=Get OTP', timeout=3000)
            
            # 4. OTP भेजे जाने का इंतज़ार करें (5 सेकंड का टाइमआउट)
            try:
                page.wait_for_selector('text=OTP has been sent', timeout=5000)
            except:
                return {"status": "error", "message": "OTP send होने में समय लग रहा है या नंबर रजिस्टर्ड नहीं है।"}

            # अगर सिर्फ OTP भेजना है
            if not otp:
                return {"status": "success", "message": f"OTP sent successfully to {number}"}
            
            # 5. OTP वेरिफिकेशन (सुपरफास्ट तरीका)
            otp_inputs = page.locator('input[maxlength="1"]')
            if otp_inputs.count() > 0:
                # पहले बॉक्स पर क्लिक करें और पूरा OTP एक साथ टाइप करें
                otp_inputs.first.click(timeout=3000)
                page.keyboard.type(otp)
            else:
                return {"status": "error", "message": "OTP इनपुट बॉक्स नहीं मिले।"}
            
            # 6. Validate OTP बटन पर क्लिक करें
            page.click('text=Validate OTP', timeout=3000)
            
            # 7. लॉगिन सफल होने का इंतज़ार करें (5 सेकंड का टाइमआउट)
            try:
                page.wait_for_selector('text=My Reports', timeout=5000)
                return {"status": "success", "message": "OTP verified and login successful! Session cleared."}
            except:
                return {"status": "error", "message": "गलत OTP या लॉगिन फेल हो गया।"}
                
        except Exception as e:
            return {"status": "error", "message": f"Automation Error: {str(e)}"}
        finally:
            # ब्राउज़र पूरी तरह बंद करें (मेमोरी क्लियर हो जाएगी)
            browser.close()

@app.route('/sent', methods=['GET'])
def sent_otp():
    key = request.args.get('key')
    if key != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid Key"}), 401

    number = request.args.get('number')
    if not number:
        return jsonify({"status": "error", "message": "Mobile number is required"}), 400
    
    result = run_playwright_flow(number)
    return jsonify(result)

@app.route('/verify', methods=['GET'])
def verify_otp():
    key = request.args.get('key')
    if key != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid Key"}), 401

    number = request.args.get('number')
    otp = request.args.get('otp')
    
    if not number or not otp:
        return jsonify({"status": "error", "message": "Both number and OTP are required"}), 400
    
    result = run_playwright_flow(number, otp)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
