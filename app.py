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

# Concurrent Request Control (Server Crash se bachane ke liye)
MAX_CONCURRENT_REQUESTS = 5
request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

def get_clean_number(number: str) -> str:
    """Number me se strictly last 10 digits nikalega"""
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-10:] if len(digits) >= 10 else digits

async def cleanup_loop():
    """Background task: Old sessions close karke RAM free rakhta hai"""
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
# STEP 1: OTP Send Request (OLD WORKING SYSTEM)
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

        # Har request ke liye naya isolated context (Bina Cache Conflict)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 360, "height": 640}
        )
        
        # Speed Booster: Images, Stylesheets, Fonts Block
        await context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_()
        )
        
        page = await context.new_page()

        try:
            await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=25000)
            
            # Aapka Original Native Fill Method
            phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
            await phone_input.fill(clean_num, timeout=10000)
            
            # Aapka Original Native Click Method
            await page.click('text=Get OTP', timeout=10000)
            
            # Asli Success Text ka wait karna
            await page.wait_for_selector('text=OTP has been sent', state='visible', timeout=15000)
            
            # Session Save
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
# STEP 2: 100% Accurate OTP Verification (JS INJECTION + FALLBACK)
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
        # 1. OTP भरने का सबसे सटीक तरीका (React ko Force Update karne ke liye)
        success_fill = await page.evaluate("""(otp) => {
            const inputs = document.querySelectorAll('input[maxlength="1"]');
            if (inputs.length >= otp.length) {
                for (let i = 0; i < otp.length; i++) {
                    inputs[i].value = otp[i];
                    inputs[i].dispatchEvent(new Event('input', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('change', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('keyup', { bubbles: true }));
                    inputs[i].dispatchEvent(new Event('blur', { bubbles: true }));
                }
                return true;
            }
            return false;
        }""", clean_otp)

        # Fallback: Agar JS injection fail ho jaye (bahut rare case)
        if not success_fill:
            otp_boxes = page.locator('input[maxlength="1"]')
            box_count = await otp_boxes.count()
            if box_count >= len(clean_otp):
                await otp_boxes.first.click(timeout=5000)
                for digit in clean_otp:
                    await page.keyboard.press(digit)
                    await asyncio.sleep(0.15)
            else:
                await context.close()
                return {"status": "error", "message": "OTP input boxes nahi mile."}

        # ⚡ बहुत जरूरी: OTP भरने के बाद 2 सेकंड का इंतज़ार (State Update ke liye)
        await asyncio.sleep(2)

        # 2. Validate OTP बटन पर क्लिक करें
        try:
            await page.click('text=Validate OTP', timeout=15000)
        except Exception:
            try:
                await page.click('text=Verify & Continue', timeout=15000)
            except Exception:
                # Fallback JavaScript click
                await page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button, input, a'));
                    const target = btns.find(b => (b.innerText || b.value || '').includes('Validate') || (b.innerText || b.value || '').includes('Verify'));
                    if (target) target.click();
                }""")

        # 3. Verification Status Check (Max 15 seconds)
        verified_status = "error"
        response_msg = "Galat OTP!"

        for _ in range(50):
            content = await page.content()

            # Error Check
            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            # Strict Success Check
            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome", "Dashboard"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            await asyncio.sleep(0.3)

        await context.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        try:
            await context.close()
        except:
            pass
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)