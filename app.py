from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import os
import time

app = Flask(__name__)

# Rate Limiting के लिए डिक्शनरी (नंबर -> आखिरी बार OTP भेजने का समय)
last_sent_time = {}
COOLDOWN_SECONDS = 60  # 60 सेकंड तक दोबारा OTP नहीं भेजेगा

def run_playwright_flow(number, otp=None):
    with sync_playwright() as p:
        # हेडलेस ब्राउज़र लॉन्च करें
        browser = p.chromium.launch(headless=True)
        # हर बार नया कॉन्टेक्स्ट बनाएं ताकि कोई पुराना डेटा न रहे
        context = browser.new_context()
        page = context.new_page()
        
        try:
            # 1. पेज पर जाएं (टाइमआउट कम कर दिया है ताकि फास्ट हो)
            page.goto("https://m.krsnaarpl.com/validate-login.html", timeout=20000)
            
            # 2. मोबाइल नंबर भरें
            page.fill('input[placeholder="Enter mobile No."]', number, timeout=5000)
            
            # 3. Get OTP बटन पर क्लिक करें
            page.click('text=Get OTP', timeout=5000)
            
            # 4. OTP भेजे जाने का इंतज़ार करें (अधिकतम 8 सेकंड)
            try:
                page.wait_for_selector('text=OTP has been sent', timeout=8000)
            except:
                return {"status": "error", "message": "OTP send होने में समय लग रहा है या नंबर रजिस्टर्ड नहीं है।"}

            # अगर सिर्फ OTP भेजना है (Verify नहीं करना)
            if not otp:
                return {"status": "success", "message": f"OTP sent successfully to {number}"}
            
            # 5. OTP वेरिफिकेशन का प्रोसेस
            # स्क्रीनशॉट के अनुसार 4 बॉक्स हैं (maxlength="1")
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
            
            # 7. लॉगिन सफल होने का इंतज़ार करें (जैसे "My Reports" दिखना)
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
    number = request.args.get('number')
    if not number:
        return jsonify({"status": "error", "message": "Mobile number is required"}), 400
    
    # Rate Limiting चेक करें (बार-बार OTP रोकने के लिए)
    current_time = time.time()
    if number in last_sent_time:
        time_passed = current_time - last_sent_time[number]
        if time_passed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - time_passed)
            return jsonify({
                "status": "error", 
                "message": f"कृपया {remaining} सेकंड प्रतीक्षा करें। इस नंबर पर OTP पहले ही भेजा जा चुका है।"
            }), 429

    # अगर कूलडाउन खत्म हो गया है, तो OTP भेजें
    result = run_playwright_flow(number)
    
    # अगर OTP सफलतापूर्वक भेज दिया गया, तो टाइमर सेट करें
    if result.get("status") == "success":
        last_sent_time[number] = time.time()
        
    return jsonify(result)

@app.route('/verify', methods=['GET'])
def verify_otp():
    number = request.args.get('number')
    otp = request.args.get('otp')
    
    if not number or not otp:
        return jsonify({"status": "error", "message": "Both number and OTP are required"}), 400
    
    # नोट: यहाँ हम कूलडाउन चेक नहीं कर रहे क्योंकि यूजर OTP वेरिफाई करना चाहता है।
    # लेकिन Playwright फिर से "Get OTP" क्लिक करेगा, इसलिए हम कूलडाउन को रीसेट कर देंगे ताकि यूजर ब्लॉक न हो।
    # हालांकि, अगर बहुत ज्यादा रिक्वेस्ट आ रही हैं, तो हम कूलडाउन चेक कर सकते हैं।
    
    result = run_playwright_flow(number, otp)
    
    # वेरिफिकेशन के बाद भी कूलडाउन अपडेट कर दें ताकि तुरंत दोबारा OTP न मंगाया जा सके
    if result.get("status") == "success":
        last_sent_time[number] = time.time()
        
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
