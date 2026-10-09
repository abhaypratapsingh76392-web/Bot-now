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

active_sessions = {}
sessions_lock = asyncio.Lock()
SESSION_TIMEOUT = 180  # 3 minutes auto-cleanup

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Expired sessions close karke RAM free rakhta hai"""
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
# STEP 1: OTP Send Request
# -------------------------------------------------------------
@app.get("/sent")
async def sent_otp(key: str = Query(None), number: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    
    clean_num = get_clean_number(number)
    if not clean_num or len(clean_num) != 10:
        return {"status": "error", "message": "Valid 10-digit mobile number required"}

    async with sessions_lock:
        if clean_num in active_sessions:
            try:
                await active_sessions[clean_num]["context"].close()
            except Exception:
                pass
            del active_sessions[clean_num]

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
    )
    
    page = await context.new_page()

    try:
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=15000)
        
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(clean_num, timeout=10000)
        
        await page.get_by_text("Get OTP").first.click(timeout=8000)
        await page.wait_for_selector('text=OTP has been sent', timeout=12000)
        
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
# STEP 2: 100% Real Verification (No Fake Success)
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
        otp_inputs = page.locator('input[maxlength="1"]')
        box_count = await otp_inputs.count()

        if box_count >= len(clean_otp):
            # Box 0 = Digit 0, Box 1 = Digit 1, Box 2 = Digit 2, Box 3 = Digit 3
            for i in range(len(clean_otp)):
                box = otp_inputs.nth(i)
                digit = clean_otp[i]
                
                await box.fill(digit)
                await box.evaluate("""el => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('keyup', { bubbles: true }));
                }""")
                await asyncio.sleep(0.08)
        else:
            await context.close()
            return {"status": "error", "message": "OTP input box nahi mila."}

        # Validate Button Click
        try:
            btn = page.locator('button:has-text("Validate OTP"), button:has-text("Verify & Continue"), input[value="Validate OTP"]').first
            await btn.click(timeout=5000)
        except Exception:
            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, input, a'));
                const target = btns.find(b => (b.innerText || b.value || '').includes('Validate OTP'));
                if (target) target.click();
            }""")

        # ---------------------------------------------------------
        # REAL VERIFICATION CHECK (STRICT LOGIC)
        # ---------------------------------------------------------
        verified_status = "error"
        response_msg = "Galat OTP!"

        start_time = time.time()
        while time.time() - start_time < 10:
            content = await page.content()

            # 1. Pehle Error Check (Red Popup 'Galat OTP!' or 'Invalid')
            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            # 2. Strict Real Success Elements Check
            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            await asyncio.sleep(0.4)

        await context.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
