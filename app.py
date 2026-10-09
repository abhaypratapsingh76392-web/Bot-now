import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from playwright.async_api import async_playwright

SECRET_KEY = "Akshay12apidev"

playwright_instance = None
browser = None

# RAM bachane ke liye ek baar me sirf 1 active process allow karega
lock = asyncio.Semaphore(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser
    playwright_instance = await async_playwright().start()
    
    # Low RAM servers (Render/Heroku) ke liye Ultra-lightweight Chromium flags
    browser = await playwright_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--single-process",
            "--disable-gpu"
        ]
    )
    yield
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()

app = FastAPI(lifespan=lifespan)

async def run_playwright_flow(number: str, otp: str = None):
    async with lock:  # Memory overload hone se bachane ke liye lock
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        # Speed Booster: CSS, Images, Fonts, Media block karna
        await context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_()
        )

        page = await context.new_page()

        try:
            # 1. Fast Page Load (wait_until='commit' se request start hote hi aage badhta hai)
            await page.goto("https://m.krsnaarpl.com/validate-login.html", timeout=12000, wait_until="commit")

            # 2. Fill Mobile Number
            phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
            await phone_input.wait_for(timeout=8000)
            await phone_input.fill(number)

            # 3. Click Get OTP
            get_otp_btn = page.locator('text=Get OTP, button:has-text("Get OTP")').first
            await get_otp_btn.click(timeout=5000)

            # 4. Wait for OTP Sent text
            try:
                await page.wait_for_selector('text=OTP has been sent', timeout=8000)
            except:
                return {"status": "error", "message": "OTP send hone me time lag raha hai ya number registered nahi hai."}

            if not otp:
                return {"status": "success", "message": f"OTP sent successfully to {number}"}

            # 5. Fill OTP (Fast Type)
            otp_inputs = page.locator('input[maxlength="1"]')
            if await otp_inputs.count() > 0:
                await otp_inputs.first.click(timeout=3000)
                await page.keyboard.type(otp)
            else:
                return {"status": "error", "message": "OTP input box nahi mila."}

            # 6. Click Validate OTP
            val_btn = page.locator('text=Validate OTP, button:has-text("Validate OTP")').first
            await val_btn.click(timeout=5000)

            # 7. Check Success
            try:
                await page.wait_for_selector('text=My Reports', timeout=8000)
                return {"status": "success", "message": "OTP verified and login successful!"}
            except:
                return {"status": "error", "message": "Galat OTP ya login fail ho gaya."}

        except Exception as e:
            return {"status": "error", "message": f"Automation Error: {str(e)}"}
        finally:
            await context.close()  # Memory instantly clear hogi

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Server is awake"}

@app.get("/sent")
async def sent_otp(key: str = Query(...), number: str = Query(...)):
    if key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Key")
    return await run_playwright_flow(number)

@app.get("/verify")
async def verify_otp(key: str = Query(...), number: str = Query(...), otp: str = Query(...)):
    if key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Key")
    return await run_playwright_flow(number, otp)
