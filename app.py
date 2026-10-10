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

# Concurrent Request Control (Render CPU Crash se bachane ke liye)
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
    
    # Fast Shared Browser Context
    shared_context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 360, "height": 640}
    )
    
    # Speed Booster: Images, Media, aur Fonts Block
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
# STEP 1: OTP Send Request (Aapka Same Code)
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

        # Har mobile request ke liye alag isolated TAB
        page = await shared_context.new_page()

        try:
            # High Timeout (25s) for Render Server Delays
            await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=25000)
            
            # Fast JS Injection for Number Fill
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

            # Click Get OTP
            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, a, input, div'));
                const target = btns.find(b => (b.innerText || b.value || '').includes('Get OTP'));
                if (target) target.click();
            }""")

            # Fast Polling for Confirmation
            otp_sent = False
            for _ in range(40):  # Max 12s polling
                content = await page.content()
                if "OTP has been sent" in content or "sent" in content.lower():
                    otp_sent = True
                    break
                await asyncio.sleep(0.3)

            if not otp_sent:
                await page.close()
                return {"status": "error", "message": "OTP send timeout! Mobile number check karein."}

            # Map active tab to mobile number
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
# STEP 2: Precise Digit-by-Digit OTP Fill (Yaha changes kiye hain)
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
        # === 100% ACCURATE OTP FILL SYSTEM (Keyboard Type) ===
        otp_boxes = page.locator('input[maxlength="1"]')
        box_count = await otp_boxes.count()
        
        if box_count > 0:
            # Pehle box par click karke usko focus me late hain
            await otp_boxes.first.click(timeout=5000)
            
            # Asli keyboard jaise ek-ek digit type karte hain
            for digit in clean_otp:
                await page.keyboard.press(digit)
                await asyncio.sleep(0.1) # Thoda delay zaruri hai website ko samajhne ke liye
        else:
            await page.close()
            return {"status": "error", "message": "OTP input boxes nahi mile."}
        
        await asyncio.sleep(0.5) # Button click se pehle OTP register hone ka wait karein

        # Click Validate OTP
        await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, input, a'));
            const target = btns.find(b => {
                const text = (b.innerText || b.value || '').toLowerCase();
                return text.includes('validate') || text.includes('verify') || text.includes('submit');
            });
            if (target) target.click();
        }""")

        # Verification Status Check
        verified_status = "error"
        response_msg = "Galat OTP!"

        for _ in range(35):  # Max 10s wait
            content = await page.content()

            # Strict Success Check (Pehle check karte hain)
            if any(succ in content for succ in ["My Reports", "Logout", "My Profile", "Welcome", "Dashboard"]):
                verified_status = "success"
                response_msg = "OTP verified successfully!"
                break

            # Error Check
            if any(err in content for err in ["Galat OTP", "Invalid OTP", "Incorrect OTP", "Expired"]):
                verified_status = "error"
                response_msg = "Galat OTP!"
                break

            await asyncio.sleep(0.3)

        await page.close()
        return {"status": verified_status, "message": response_msg}

    except Exception as e:
        await page.close()
        return {"status": "error", "message": f"Automation Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
