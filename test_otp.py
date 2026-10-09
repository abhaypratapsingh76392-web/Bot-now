import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # हेडलेस क्रोमियम ब्राउज़र लॉन्च करें
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # टारगेट पेज पर जाएं
        await page.goto("https://m.krsnaarpl.com/validate-login.html")
        
        # मोबाइल नंबर इनपुट फ़ील्ड में नंबर भरें
        await page.fill('input[placeholder="Enter mobile No."]', '9335565511')
        
        # "Get OTP" बटन पर क्लिक करें
        await page.click('text=Get OTP')
        
        # सफलता संदेश या OTP इनपुट फ़ील्ड के दिखने का इंतज़ार करें (अधिकतम 10 सेकंड)
        try:
            await page.wait_for_selector('text=OTP has been sent', timeout=10000)
            print("✅ OTP sent successfully to 9335565511")
        except Exception as e:
            print("❌ Failed to send OTP. Error:", str(e))
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
