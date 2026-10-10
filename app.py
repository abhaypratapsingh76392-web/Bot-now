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
shared_context = None

# Single shared session store
active_sessions = {}
sessions_lock = asyncio.Lock()
SESSION_TIMEOUT = 180  # 3 minutes cleanup

# Concurrent Request Control
MAX_CONCURRENT_REQUESTS = 5
request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Old unused tabs ko close karke RAM free rakhta hai"""
    while True:
        await asyncio.sleep(20)
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
                        await sess["page"].close()
                    except Exception:
                        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser, shared_context
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
    
    shared_context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    await shared_context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "font", "media", "other"] else route.continue_()
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
# STEP 1: OTP Send Request
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
                    await active_sessions[clean_num]["page"].close()
                except Exception:
                    pass
                del active_sessions[clean_num]

        page = await shared_context.new_page()

        try:
            await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=25000)
            
            filled = await page.evaluate("""(num) => {
                const input = document.querySelector('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]');
                if (input) {
                    input.value = num;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }""", clean_num)

            if not filled:
                phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
                await phone_input.fill(clean_num, timeout=8000)

            try:
                await page.click('text=Get OTP', timeout=10000)
            except Exception:
                await page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button, a, input, div'));
                    const target = btns.find(b => (b.innerText || b.value || '').includes('Get OTP'));
                    if (target) target.click();
                }""")

            otp_sent = False
            for _ in range(40):
                content = await page.content()
                if "OTP has been sent" in content:
                    otp_sent = True
                    break
                try:
                    if await page.locator('input[maxlength="1"]').count() > 0:
                        otp_sent = True
                        break
                except:
                    pass
                await asyncio.sleep(0.3)

            if not otp_sent:
                await page.close()
                return {"status": "error", "message": "OTP send timeout! Mobile number check karein ya thodi der baad try karein."}

            async with sessions_lock:
                active_sessions[clean_num] = {
                    "page": page,
                    "created_at": time.time()
                }
            
            return {"status": "success", "message": f"OTP sent successfully to {clean_num}"}

        except Exception as e:
            await page.close()
            return {"status": "error", "message": f"Automation Error: {str(e)}"}

# -------------------------------------------------------------
# STEP 2: Precise Digit-by-Digit OTP Fill & Verification (FIXED)
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

    page = session["page"]

    try:
        # 1. OTP भरने का तरीका (JS Injection + Keyboard Fallback)
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

        if not success_fill:
            otp_inputs = page.locator('input[maxlength="1"]')
            if await otp_inputs.count() >= len(clean_otp):
                await otp_inputs.first.click()
                for digit in clean_otp:
                    await page.keyboard.press(digit)
                    await asyncio.sleep(0.1)
            else:
                await page.close()
                return {"status": "error", "message": "OTP input boxes nahi mile."}

        # ✅ FIX 1: थोड़ा इंतज़ार करें ताकि React State अपडेट हो जाए
        await asyncio.sleep(1.5)

        # ✅ FIX 2: बटन क्लिक करने के लिए टाइमआउट बढ़ाकर 15 सेकंड करें
        try:
            await page.click('text=Validate OTP', timeout=15000)
        except Exception:
            try:
                await page.click('text=Verify & Continue', timeout=15000)
            except Exception:
                # अगर बटन न मिले तो कोड क्रैश न हो, बस आगे बढ़े
                pass

        # ✅ FIX 3: रिस्पॉन्स का इंतज़ार बढ़ाकर 15 सेकंड करें
        verified_status = "error"
        response_msg = "Galat OTP!"

        for _ in range(50):  # Max 15s wait
            content = await page.content()

            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            await asyncio.sleep(0.3)

        await page.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        try:
            await page.close()
        except:
            pass
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)