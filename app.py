import os
import asyncio
import time
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
# STEP 1: OTP Send Request (Browser Context Open Rakhega)
# -------------------------------------------------------------
@app.get("/sent")
async def sent_otp(key: str = Query(None), number: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number:
        return {"status": "error", "message": "Mobile number is required"}

    async with sessions_lock:
        if number in active_sessions:
            try:
                await active_sessions[number]["context"].close()
            except Exception:
                pass
            del active_sessions[number]

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    # Extra styles/images block for 3-5s speed
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
    )
    
    page = await context.new_page()

    try:
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=15000)
        
        # Mobile Number Fill
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(number, timeout=10000)
        
        # Click Get OTP
        await page.click('text=Get OTP', timeout=8000)
        
        # Wait for OTP Sent text
        await page.wait_for_selector('text=OTP has been sent', timeout=12000)
        
        # Session Store
        async with sessions_lock:
            active_sessions[number] = {
                "context": context,
                "page": page,
                "created_at": time.time()
            }
        
        return {"status": "success", "message": f"OTP sent successfully to {number}"}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

# -------------------------------------------------------------
# STEP 2: 100% Accurate OTP Verification
# -------------------------------------------------------------
@app.get("/verify")
async def verify_otp(key: str = Query(None), number: str = Query(None), otp: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number or not otp:
        return {"status": "error", "message": "Both number and otp are required"}

    async with sessions_lock:
        session = active_sessions.pop(number, None)

    if not session:
        return {"status": "error", "message": "Pehle /sent call karein ya session expire ho gaya hai."}

    context = session["context"]
    page = session["page"]

    try:
        # 1. Direct JS Injection - Har box me digit set karke event trigger karega
        await page.evaluate("""(otp_str) => {
            const inputs = document.querySelectorAll('input[maxlength="1"]');
            if (inputs.length >= otp_str.length) {
                for (let i = 0; i < otp_str.length; i++) {
                    inputs[i].value = otp_str[i];
                    inputs[i].dispatchEvent(new Event('input', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('change', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('blur', { bubbles: true }));
                }
            }
        }""", str(otp))

        # 2. Backup Keyboard Typing (JS Events miss hone se bachane ke liye)
        otp_inputs = page.locator('input[maxlength="1"]')
        if await otp_inputs.count() >= len(otp):
            await otp_inputs.first.click()
            for digit in str(otp):
                await page.keyboard.press(digit)
                await asyncio.sleep(0.08)  # Chhota delay taaki site ka React/Vue state update ho jaye
        
        # 3. Click Validate OTP Button
        validate_btn = page.locator('button:has-text("Validate OTP"), text=Validate OTP, input[value="Validate OTP"]').first
        await validate_btn.click(timeout=6000)

        # 4. Success Check
        try:
            await page.wait_for_selector('text=My Reports, text=Logout, text=Welcome', timeout=8000)
            await context.close()
            return {"status": "success", "message": "OTP verified successfully!"}
        except Exception:
            # Error Check
            error_text = "Galat OTP ya login failed."
            if await page.locator('text=Invalid OTP, text=Incorrect, text=Galat').count() > 0:
                error_text = "Galat OTP!"
            
            await context.close()
            return {"status": "error", "message": error_text}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}
