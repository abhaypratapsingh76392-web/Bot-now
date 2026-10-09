import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from playwright.async_api import async_playwright

SECRET_KEY = "Akshay12apidev"

playwright_instance = None
browser = None

# Server start hote hi browser ready rakhega
@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser
    playwright_instance = await async_playwright().start()
    browser = await playwright_instance.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    yield
    await browser.close()
    await playwright_instance.stop()

app = FastAPI(lifespan=lifespan)

async def run_playwright_flow(number: str, otp: str = None):
    # Har request ke liye sirf ek lightweight Browser Context khulega (Instant execution)
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # Images, Fonts, Media aur CSS ko block karke loading super fast ki gayi hai
    await context.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_()
    )

    page = await context.new_page()

    try:
        # 1. Open Page (DomContentLoaded mode fast load deta hai)
        await page.goto("https://m.krsnaarpl.com/validate-login.html", timeout=10000, wait_until="domcontentloaded")

        # 2. Fill Mobile Number
        try:
            await page.fill('input[placeholder="Enter mobile No."]', number, timeout=4000)
        except:
            try:
                await page.fill('input[type="tel"]', number, timeout=2000)
            except:
                await page.fill('input[type="text"]', number, timeout=2000)

        # 3. Click Get OTP
        try:
            await page.click('text=Get OTP', timeout=4000)
        except:
            await page.click('button:has-text("Get OTP")', timeout=2000)

        # 4. Wait for OTP Sent
        try:
            await page.wait_for_selector('text=OTP has been sent', timeout=6000)
        except:
            return {"status": "error", "message": "OTP send hone me time lag raha hai ya number registered nahi hai."}

        if not otp:
            return {"status": "success", "message": f"OTP sent successfully to {number}"}

        # 5. Fill OTP
        otp_inputs = page.locator('input[maxlength="1"]')
        if await otp_inputs.count() > 0:
            await otp_inputs.first.click(timeout=2000)
            await page.keyboard.type(otp)
        else:
            return {"status": "error", "message": "OTP input box nahi mila."}

        # 6. Click Validate OTP
        try:
            await page.click('text=Validate OTP', timeout=4000)
        except:
            await page.click('button:has-text("Validate OTP")', timeout=2000)

        # 7. Check Login Success
        try:
            await page.wait_for_selector('text=My Reports', timeout=6000)
            return {"status": "success", "message": "OTP verified and login successful!"}
        except:
            return {"status": "error", "message": "Galat OTP ya login fail ho gaya."}

    except Exception as e:
        return {"status": "error", "message": f"Automation Error: {str(e)}"}
    finally:
        await context.close()

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
