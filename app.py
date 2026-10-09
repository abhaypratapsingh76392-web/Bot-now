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
SESSION_TIMEOUT = 180  # 3 minutes me unused tab auto-close

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Expired tabs close karke RAM free rakhta hai"""
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
    
    # Pre-warmed Shared Context (Fast Tab Creation)
    shared_context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    # Speed Booster: Unnecessary Network Assets Block
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
# STEP 1: Superfast OTP Send (3-5 Seconds Target)
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

    # Concurrent Multi-Tab Page Creation
    page = await shared_context.new_page()

    try:
        # Fast DOM load
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=12000)
        
        # JS Injection for Instant Number Filling
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
            await phone_input.fill(clean_num, timeout=5000)

        # Trigger Get OTP
        await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, a, input, div'));
            const target = btns.find(b => (b.innerText || b.value || '').includes('Get OTP'));
            if (target) target.click();
        }""")

        # Fast 0.2s Polling Loop for 'OTP has been sent'
        otp_sent = False
        for _ in range(35):  # Max 7 seconds timeout
            content = await page.content()
            if "OTP has been sent" in content or "sent" in content.lower():
                otp_sent = True
                break
            await asyncio.sleep(0.2)

        if not otp_sent:
            await page.close()
            return {"status": "error", "message": "OTP send timeout: Mobile number check karein"}

        # Store Session Mapping
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
# STEP 2: Instant Single-Shot OTP Verification (2-4 Seconds Target)
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
        # ⚡ SINGLE-SHOT JS INJECTION (Sabhi 4 boxes me ek sath 10ms me fill karega)
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
            await page.close()
            return {"status": "error", "message": "OTP input boxes nahi mile."}

        # Validate OTP Click via JS
        await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, input, a'));
            const target = btns.find(b => (b.innerText || b.value || '').includes('Validate OTP'));
            if (target) target.click();
        }""")

        # Fast 0.2s Response Polling Check
        verified_status = "error"
        response_msg = "Galat OTP!"

        for _ in range(30):  # Max 6 seconds wait
            content = await page.content()

            # Error Check First
            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            # Strict Real Success Check
            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            await asyncio.sleep(0.2)

        await page.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        await page.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
