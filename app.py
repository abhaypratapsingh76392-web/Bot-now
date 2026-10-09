from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import os

app = Flask(__name__)

# 🔒 नई Secret Key
SECRET_KEY = "Akshay12apidev"

def run_playwright_flow(number, otp=None):
    with sync_playwright() as p:
        # हेडलेस ब्राउज़र लॉन्च करें
        browser = p.chromium.launch(headless=True)
        # हर बार नया कॉन्टेक्स्ट बनाएं ताकि कोई पुराना डेटा न रहे (ऑटो लॉगआउट)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            # 1. पेज पर जाएं
            page.goto("https://m.krsnaarpl.com/validate-login.html", timeout=20000)
            
            # 2. सिर्फ उसी नंबर को भरें जो रिक्वेस्ट में आया है
            page.fill('input[placeholder="Enter mobile No."]', number, timeout=5000)
            
            # 3. Get OTP बटन पर क्लिक करें
            page.click('text=Get OTP', timeout=5000)
            
            # 4. OTP भेजे जाने का इंतज़ार करें
            try:
                page.wait_for_selector('text=OTP has been sent', timeout=8000)
            except:
                return {"status": "error", "message": "OTP send होने में समय लग रहा है या नंबर रजिस्टर्ड नहीं है।"}

            # अगर सिर्फ OTP भेजना है (Verify नहीं करना)
            if not otp:
                return {"status": "success", "message": f"OTP sent successfully to {number}"}
            
            # 5. OTP वेरिफिकेशन का प्रोसेस
            otp_inputs = page.locator('input[maxlength="1"]')
            count = otp_inputs.count()
            
            if count == 0:
                return {"status": "error", "message": "OTP इनपुट बॉक्स नहीं मिले।"}

            # OTP के अंकों को बॉक्स में भरें
            for i, digit in enumerate(otp):
                if i < count:
                    otp_inputs.nth(i).fill(digit)
            
            # 6. Validate OTP बटन पर क्लिक करें
            page.click('text=Validate OTP', timeout=5000)
            
            # 7. लॉगिन सफल होने का इंतज़ार करें
            try:
                page.wait_for_selector('text=My Reports', timeout=10000)
                return {"status": "success", "message": "OTP verified and login successful! Session cleared."}
            except:
                return {"status": "error", "message": "गलत OTP या लॉगिन फेल हो गया।"}
                
        except Exception as e:
            return {"status": "error", "message": f"Automation Error: {str(e)}"}
        finally:
            # ब्राउज़र बंद करें (इससे सारा डेटा/कुकीज़/लॉगिन अपने आप क्लियर हो जाता है)
            browser.close()

@app.route('/sent', methods=['GET'])
def sent_otp():
    # 🔒 की (Key) चेक करें
    key = request.args.get('key')
    if key != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid Key"}), 401

    number = request.args.get('number')
    if not number:
        return jsonify({"status": "error", "message": "Mobile number is required"}), 400
    
    # सीधे OTP भेजें (कोई कूलडाउन नहीं, जितनी बार चाहें उतनी बार)
    result = run_playwright_flow(number)
    return jsonify(result)

@app.route('/verify', methods=['GET'])
def verify_otp():
    # 🔒 की (Key) चेक करें
    key = request.args.get('key')
    if key != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid Key"}), 401

    number = request.args.get('number')
    otp = request.args.get('otp')
    
    if not number or not otp:
        return jsonify({"status": "error", "message": "Both number and OTP are required"}), 400
    
    # सीधे OTP वेरिफाई करें
    result = run_playwright_flow(number, otp)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
