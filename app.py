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
SESSION_TIMEOUT = 180  # 3 minutes me auto cleanup

def get_clean_number(number: str) -> str:
    """Number me se +91, spaces aur special characters hatakar sirf last 10 digits nikalega"""
    digits = re.sub(r'\D', '', number or '')
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: RAM free rakhne ke liye old sessions close karega"""
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
# STEP 1: OTP Send Request (Clean 10-digit Session Open)
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
    
    # Fast load: Unnecessary resources block
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
    )
    
    page = await context.new_page()

    try:
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=15000)
        
        # Mobile Number Fill
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(clean_num, timeout=10000)
        
        # Click Get OTP
        await page.click('text=Get OTP', timeout=8000)
        
        # Wait for OTP Sent text
        await page.wait_for_selector('text=OTP has been sent', timeout=12000)
        
        # Save session with exact 10-digit key
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
# STEP 2: Precise Real Keyboard OTP Verification
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

        if box_count > 0:
            # 1. Pehle OTP box par focus karein
            await otp_inputs.first.click()
            await asyncio.sleep(0.1)
            
            # 2. Sequential Real Keyboard Presses (Target site ke JS KeyUp/KeyDown triggers ke liye)
            for char in clean_otp:
                await page.keyboard.press(char)
                await asyncio.sleep(0.12)
                
            # 3. Krsnaa Frontend JS State Sync ke liye 0.5s wait
            await asyncio.sleep(0.5)
        else:
            await context.close()
            return {"status": "error", "message": "OTP input box nahi mil saka."}

        # Click Validate OTP Button
        validate_btn = page.locator('button:has-text("Validate OTP"), text=Validate OTP, input[value="Validate OTP"]').first
        await validate_btn.click(timeout=6000)

        # Success Check
        try:
            await page.wait_for_selector('text=My Reports, text=Logout, text=Welcome', timeout=8000)
            await context.close()
            return {"status": "success", "message": "OTP verified successfully!"}
        except Exception:
            await context.close()
            return {"status": "error", "message": "Galat OTP!"}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}
