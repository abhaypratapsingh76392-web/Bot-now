import os
import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from playwright.async_api import async_playwright

SECRET_KEY = "Akshay12apidev"

playwright_instance = None
browser = None

# Active Sessions mapping: number -> {"context": context, "page": page, "created_at": time}
active_sessions = {}
sessions_lock = asyncio.Lock()
SESSION_TIMEOUT = 180  # 3 minutes me session auto-close ho jayega RAM bachane ke liye

# Background task: Expired sessions clean karna
async def cleanup_loop():
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

# STEP 1: OTP Send karega aur Session Open rakhega
@app.get("/sent")
async def sent_otp(key: str = Query(None), number: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number:
        return {"status": "error", "message": "Mobile number is required"}

    # Agar same number ka purana session h to use close kar do
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
    
    # Extra resources block for fast loading
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
    )
    
    page = await context.new_page()

    try:
        # 1. Open URL
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=15000)
        
        # 2. Fill Mobile Number
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(number, timeout=10000)
        
        # 3. Click Get OTP
        await page.click('text=Get OTP', timeout=8000)
        
        # 4. Wait for OTP Sent
        await page.wait_for_selector('text=OTP has been sent', timeout=12000)
        
        # Session ko save kar lo taaki /verify same page use kare
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


# STEP 2: Pre-opened Session par fast OTP verify karega
@app.get("/verify")
async def verify_otp(key: str = Query(None), number: str = Query(None), otp: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number or not otp:
        return {"status": "error", "message": "Both number and OTP are required"}

    async with sessions_lock:
        session = active_sessions.pop(number, None)

    if not session:
        return {"status": "error", "message": "Pehle /sent call karke OTP bhejiye ya session expire ho gaya."}

    context = session["context"]
    page = session["page"]

    try:
        # Direct OTP Fill (No page reloading)
        otp_inputs = page.locator('input[maxlength="1"]')
        if await otp_inputs.count() > 0:
            await otp_inputs.first.click(timeout=3000)
            await page.keyboard.type(otp)
        else:
            await context.close()
            return {"status": "error", "message": "OTP input box nahi mila."}

        # Click Validate OTP
        await page.click('text=Validate OTP', timeout=6000)

        # Check Login Success
        try:
            await page.wait_for_selector('text=My Reports', timeout=8000)
            await context.close()
            return {"status": "success", "message": "OTP verified successfully!"}
        except Exception:
            await context.close()
            return {"status": "error", "message": "Galat OTP ya login failed."}

    except Exception as e:
        await context.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}
