import os
import asyncio
import time
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from playwright.async_api import async_playwright

SECRET_KEY = "Akshay12apidev"

playwright_instance = None
browser = None

# Active Sessions: number -> {"context": context, "page": page, "created_at": time}
active_sessions = {}
sessions_lock = asyncio.Lock()
SESSION_TIMEOUT = 180  # 3 minutes me auto cleanup

# Concurrent Request Control (CPU Crash se bachane ke liye)
MAX_CONCURRENT_REQUESTS = 5
request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Old sessions close karke RAM bilkul free rakhta hai"""
    while True:
        await asyncio.sleep(30)
        now = time.time()
        async with sessions_lock:
            expired_numbers = [
                num for num, sess in active_sessions.items()
                if now - sess["created_at"] > SESSION_TIMEOUT
            ]
            for num in expired_numbers:
                sess = active_sessions.pop(num, None)
                if sess:
                    try:
                        await sess["context"].close()
                    except Exception:
                        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser
    playwright_instance = await async_playwright().start()
    
    browser = await playwright_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--blink-settings=imagesEnabled=false"
        ]
    )
    cleanup_task = asyncio.create_task(cleanup_loop())
    yield
    cleanup_task.cancel()
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Server active"}

# -------------------------------------------------------------
# STEP 1: OTP Send Request (तुम्हारे Old Code का सटीक तरीका)
# -------------------------------------------------------------
@app.get("/sent")
async def sent_otp(key: str = Query(None), number: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    
    clean_num = get_clean_number(number)
    if not clean_num or len(clean_num) != 10:
        return {"status": "error", "message": "Valid 10-digit mobile number required"}

    async with request_semaphore:
        async with sessions_lock:
            if clean_num in active_sessions:
                try:
                    await active_sessions[clean_num]["context"].close()
                except Exception:
                    pass
                del active_sessions[clean_num]

        # हर रिक्वेस्ट के लिए नया, साफ़ कॉन्टेक्स्ट (ताकि पुराना कुकीज़ कन्फ्लिक्ट न करें)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 360, "height": 640}
        )
        
        # ⚡ स्पीड बूस्टर
        await context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
        )
        
        page = await context.new_page()

        try:
            await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=25000)
            
            # ✅ तुम्हारे पुराने कोड का तरीका: Locator + Fill
            phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
            await phone_input.fill(clean_num, timeout=10000)
            
            # ✅ तुम्हारे पुराने कोड का तरीका: Native Click
            await page.click('text=Get OTP', timeout=10000)
            
            # ✅ तुम्हारे पुराने कोड का तरीका: Visible Text का इंतज़ार
            await page.wait_for_selector('text=OTP has been sent', state='visible', timeout=15000)
            
            # सेशन को सेव करें ताकि /verify में इसी टैब का उपयोग हो सके
            async with sessions_lock:
                active_sessions[clean_num] = {
                    "context": context,
                    "page": page,
                    "created_at": time.time()
                }
            
            return {"status": "success", "message": f"OTP sent successfully to {clean_num}"}

        except Exception as e:
            await context.close()
            return {"status": "error", "message": f"Automation Error: {str(e)}"}

# -------------------------------------------------------------
# STEP 2: 100% Accurate OTP Verification (तुम्हारे New Code का तरीका)
# -------------------------------------------------------------
@app.get("/verify")
async def verify_otp(key: str = Query(None), number: str = Query(None), otp: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
        
    clean_num = get_clean_number(number)
    clean_otp = str(otp or "").strip()

    if not clean_num or not clean_otp:
        return {"status": "error", "message": "Both number and otp are required"}

    async with sessions_lock:
        session = active_sessions.pop(clean_num, None)

    if not session:
        return {"status": "error", "message": "Pehle /sent call karein ya session expire ho gaya hai."}

    context = session["context"]
    page = session["page"]

    try:
        # ✅ तुम्हारे New Code का सटीक Digit-by-Digit JS Injection
        success_fill = await page.evaluate("""(otp) => {
            const inputs = document.querySelectorAll('input[maxlength="1"]');
            if (inputs.length >= otp.length) {
                for (let i = 0; i < otp.length; i++) {
                    inputs[i].value = otp[i];
                    inputs[i].dispatchEvent(new Event('input', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('change', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('keyup', { bubbles: true }));
                }
                return true;
            }
            return false;
        }""", clean_otp)

        # Fallback: अगर JS काम न करे तो कीबोर्ड से टाइप करें
        if not success_fill:
            otp_inputs = page.locator('input[maxlength="1"]')
            if await otp_inputs.count() >= len(clean_otp):
                await otp_inputs.first.click()
                for digit in clean_otp:
                    await page.keyboard.press(digit)
                    await asyncio.sleep(0.1)
            else:
                await context.close()
                return {"status": "error", "message": "OTP input boxes nahi mile."}

        # Validate OTP Button पर क्लिक करें
        try:
            await page.click('text=Validate OTP', timeout=10000)
        except Exception:
            await page.click('text=Verify & Continue', timeout=5000)

        # Response का इंतज़ार करें (Success या Error)
        await asyncio.sleep(3)

        # Success Check
        success_found = False
        for selector in ['text=My Reports', 'text=Logout', 'text=Dashboard', 'text=Welcome', 'text=My Profile']:
            if await page.locator(selector).count() > 0:
                success_found = True
                break

        if success_found:
            await context.close()
            return {"status": "success", "message": "OTP verified successfully! Login ho gaya."}

        # Error Check
        error_text = "Galat OTP ya login failed."
        if await page.locator('text=Invalid OTP').count() > 0 or await page.locator('text=Galat OTP').count() > 0:
            error_text = "Invalid OTP! Kripya sahi OTP dalein."
        elif await page.locator('text=Expired').count() > 0:
            error_text = "OTP expire ho gaya hai. Kripya naya OTP bhijwayein."

        await context.close()
        return {"status": "error", "message": error_text}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)