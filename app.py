import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from playwright.async_api import async_playwright

SECRET_KEY = "Akshay12apidev"

playwright_instance = None
browser = None
semaphore = asyncio.Semaphore(1)

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
    yield
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()

app = FastAPI(lifespan=lifespan)

async def run_flow(number: str, otp: str = None):
    async with semaphore:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 360, "height": 640}
        )
        
        # Superfast Loading: Unnecessary resource request cancel karna
        await context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"] else route.continue_()
        )
        
        page = await context.new_page()
        
        try:
            # 1. Open URL
            await page.goto("https://m.krsnaarpl.com/validate-login.html", wait_until="domcontentloaded", timeout=15000)
            
            # 2. Fill Mobile Number (Corrected locator syntax)
            phone_input = page.locator('input[placeholder="Enter mobile No."], input[type="tel"], input[type="text"]').first
            await phone_input.wait_for(timeout=5000)
            await phone_input.fill(number)
            
            # 3. Click Get OTP
            await page.click('text=Get OTP', timeout=5000)
            
            # 4. Wait for Sent Message
            try:
                await page.wait_for_selector('text=OTP has been sent', timeout=8000)
            except Exception:
                await context.close()
                return {"status": "error", "message": "OTP send nahi hua ya timeout ho gaya."}
            
            if not otp:
                await context.close()
                return {"status": "success", "message": f"OTP sent successfully to {number}"}
            
            # 5. Fill OTP
            otp_inputs = page.locator('input[maxlength="1"]')
            if await otp_inputs.count() > 0:
                await otp_inputs.first.click(timeout=3000)
                await page.keyboard.type(otp)
            else:
                await context.close()
                return {"status": "error", "message": "OTP input box nahi mila."}
            
            # 6. Validate OTP
            await page.click('text=Validate OTP', timeout=5000)
            
            try:
                await page.wait_for_selector('text=My Reports', timeout=8000)
                await context.close()
                return {"status": "success", "message": "OTP verified successfully!"}
            except Exception:
                await context.close()
                return {"status": "error", "message": "Wrong OTP ya login failed."}
                
        except Exception as e:
            await context.close()
            return {"status": "error", "message": f"Automation Error: {str(e)}"}

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Server active"}

@app.get("/sent")
async def sent_otp(key: str = Query(None), number: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number:
        return {"status": "error", "message": "Mobile number is required"}
    return await run_flow(number)

@app.get("/verify")
async def verify_otp(key: str = Query(None), number: str = Query(None), otp: str = Query(None)):
    if key != SECRET_KEY:
        return {"status": "error", "message": "Unauthorized: Invalid Key"}
    if not number or not otp:
        return {"status": "error", "message": "Both number and OTP are required"}
    return await run_flow(number, otp)
