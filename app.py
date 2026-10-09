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

active_sessions = {}
sessions_lock = asyncio.Lock()
SESSION_TIMEOUT = 180  # 3 minutes me unused tab auto-close hoga

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Expired tabs ko close karke RAM free rakhta hai"""
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
    
    # Single Shared Context (RAM aur CPU save karne ke liye)
    shared_context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    # Global Speed Booster (Images, CSS, Fonts block)
    await shared_context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
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
# STEP 1: OTP Send Request (Dedicated Isolated Tab Open)
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
                await active_sessions[clean_num]["page"].close()
            except Exception:
                pass
            del active_sessions[clean_num]

    # Shared Context se Naya Isolated Tab (Page) banega
    page = await shared_context.new_page()

    try:
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=25000)
        
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(clean_num, timeout=10000)
        
        await page.get_by_text("Get OTP").first.click(timeout=8000)
        await page.wait_for_selector('text=OTP has been sent', timeout=15000)
        
        # Exact Number ka Tab Mapping
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
# STEP 2: Exact Tab OTP Fill & Real Verification
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
            await page.close()
            return {"status": "error", "message": "OTP input box nahi mila."}

        # Validate Button Click
        try:
            btn = page.locator('button:has-text("Validate OTP"), button:has-text("Verify & Continue"), input[value="Validate OTP"]').first
            await btn.click(timeout=6000)
        except Exception:
            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, input, a'));
                const target = btns.find(b => (b.innerText || b.value || '').includes('Validate OTP'));
                if (target) target.click();
            }""")

        # Real Strict Verification Check
        verified_status = "error"
        response_msg = "Galat OTP!"

        start_time = time.time()
        while time.time() - start_time < 12:
            content = await page.content()

            # Error Check
            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            # Success Check
            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            await asyncio.sleep(0.4)

        await page.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        await page.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
