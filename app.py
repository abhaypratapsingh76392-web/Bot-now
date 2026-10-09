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
# STEP 1: OTP Send Request
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
    
    # ⚡ स्पीड बूस्टर: इमेज, स्टाइलशीट, फॉन्ट ब्लॉक करें
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
    )
    
    page = await context.new_page()

    try:
        await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=20000)
        
        # Mobile Number Fill
        phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
        await phone_input.fill(number, timeout=10000)
        
        # Click Get OTP
        await page.click('text=Get OTP', timeout=10000)
        
        # Wait for OTP Sent text
        await page.wait_for_selector('text=OTP has been sent', timeout=15000)
        
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
# STEP 2: 100% Accurate OTP Verification (Bug Fixed)
# -------------------------------------------------------------
@app.get("/verify")
async def verify_otp(key: str = Query(None), number: str = Query(None), otp: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number or not otp:
        return {"status": "error", "message": "Both number and otp are required"}

    # OTP ko clean karein
    otp = str(otp).strip()

    async with sessions_lock:
        session = active_sessions.pop(number, None)

    if not session:
        return {"status": "error", "message": "Pehle /sent call karein ya session expire ho gaya hai."}

    context = session["context"]
    page = session["page"]

    try:
        # 1. OTP Input Boxes ko dhoondhein
        otp_inputs = page.locator('input[maxlength="1"]')
        count = await otp_inputs.count()
        
        if count >= 4:
            # ✅ 4 Alag-alag boxes ke liye (ह्यूमन-लाइक टाइपिंग)
            for i in range(len(otp)):
                if i < count:
                    await otp_inputs.nth(i).click()
                    await otp_inputs.nth(i).fill('') # पहले खाली करें
                    await asyncio.sleep(0.1)
                    await otp_inputs.nth(i).type(otp[i], delay=150) # फिर टाइप करें
                    await asyncio.sleep(0.1)
        else:
            # ✅ Fallback: Agar single input box hai
            single_input = page.locator('input[type="tel"], input[type="text"]').nth(1)
            if await single_input.count() > 0:
                await single_input.click()
                await single_input.fill('')
                await asyncio.sleep(0.1)
                await single_input.type(otp, delay=200)
            else:
                await context.close()
                return {"status": "error", "message": "OTP input box nahi mila."}

        # 2. Validate OTP Button par click karein
        try:
            validate_btn = page.locator('button:has-text("Validate OTP"), button:has-text("Verify & Continue")').first
            await validate_btn.click(timeout=5000)
        except Exception:
            # Agar auto-submit ho gaya ho to ignore karein
            pass

        # 3. Response ka wait karein (Success ya Error)
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