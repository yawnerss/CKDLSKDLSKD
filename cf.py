import sys
import time
import os
import shutil
import glob
import logging
import subprocess
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from seleniumbase import Driver
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = "chrome_cache"

app = FastAPI(
    title="Cloudflare Cookie Solver API",
    description="Solves Cloudflare challenges and returns cf_clearance cookies",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CookieResponse(BaseModel):
    success: bool
    cookie: str = None
    url: str = None
    error: str = None

class SolveRequest(BaseModel):
    url: str
    use_cache: bool = True
    timeout: int = 30

def get_chrome_path():
    """Determine Chrome binary location with fallbacks."""
    # 1. Check environment variable
    chrome_path = os.environ.get("CHROME_PATH")
    if chrome_path and os.path.exists(chrome_path):
        logger.info(f"✅ Chrome found via CHROME_PATH: {chrome_path}")
        return chrome_path

    # 2. Auto-detect Playwright Chromium (handles version number changes)
    playwright_paths = (
        glob.glob("/opt/render/.cache/ms-playwright/chromium*/chrome-linux/chrome") +
        glob.glob("/opt/render/.cache/ms-playwright/chromium_headless_shell*/chrome-linux/headless_shell") +
        glob.glob("/home/**/.cache/ms-playwright/chromium*/chrome-linux/chrome", recursive=True) +
        glob.glob("/root/.cache/ms-playwright/chromium*/chrome-linux/chrome")
    )
    for p in playwright_paths:
        if os.path.exists(p):
            logger.info(f"✅ Chrome found via Playwright cache: {p}")
            return p

    # 3. Try relative path (./chrome/chrome-linux64/chrome)
    rel_path = os.path.join(os.getcwd(), "chrome", "chrome-linux64", "chrome")
    if os.path.exists(rel_path):
        logger.info(f"✅ Chrome found at: {rel_path}")
        return rel_path

    # 4. Try system-wide Chrome
    system_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium"
    ]
    for p in system_paths:
        if os.path.exists(p):
            logger.info(f"✅ Chrome found at system path: {p}")
            return p

    logger.error("❌ Chrome binary not found")
    return None

def get_cloudflare_cookie(url: str, use_cache: bool = True, timeout: int = 30, debug: bool = False) -> tuple:
    if not use_cache and os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR, exist_ok=True)

    chrome_path = get_chrome_path()
    if not chrome_path:
        raise Exception("Chrome binary not found. Please set CHROME_PATH environment variable.")

    # Make it executable and set environment variable for SeleniumBase
    os.chmod(chrome_path, 0o755)
    os.environ['CHROME_PATH'] = chrome_path

    driver = Driver(
        uc=True,
        headless=True,
        user_data_dir=CACHE_DIR,
        disable_gpu=True,
        no_sandbox=True
    )

    try:
        start_time = time.time()
        if debug:
            logger.info(f"Opening URL: {url}")

        driver.uc_open_with_reconnect(url, reconnect_time=0.5)

        poll_count = 0
        while time.time() - start_time < timeout:
            poll_count += 1
            try:
                current_title = driver.title or ""
                current_url = driver.current_url or ""

                if debug and poll_count % 50 == 0:
                    elapsed = time.time() - start_time
                    logger.debug(f"{elapsed:.1f}s - Title: {current_title[:50]}")

                if current_title and "Just a moment" not in current_title and "Challenge" not in current_title and len(current_title) > 0:
                    cookies = driver.get_cookies()
                    for c in cookies:
                        if c['name'] == 'cf_clearance':
                            final_url = driver.current_url
                            if debug:
                                logger.info(f"✅ Solved in {time.time() - start_time:.1f}s")
                            return c['value'], final_url
            except Exception as e:
                if debug:
                    logger.debug(f"Poll error: {str(e)}")
            time.sleep(0.01)

        final_title = driver.title or "No title"
        final_url = driver.current_url or "No URL"
        raise TimeoutError(f"Timeout after {timeout}s. Last title: '{final_title}' | URL: {final_url}")
    except Exception as e:
        raise Exception(f"Error solving Cloudflare challenge: {str(e)}")
    finally:
        try:
            driver.quit()
        except:
            pass

@app.get("/")
async def root():
    return {
        "message": "Cloudflare Cookie Solver API",
        "endpoints": {
            "POST /solve": "Solve CF challenge and get cookie",
            "GET /solve": "Query parameter version (url, use_cache, timeout)",
            "GET /health": "Health check",
            "GET /debug": "Debug Chrome path"
        },
        "example": {"url": "https://checkton.online", "use_cache": True, "timeout": 15}
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/debug")
async def debug_chrome():
    # Find all playwright cache files
    found = glob.glob("/opt/render/.cache/ms-playwright/**/*", recursive=True)

    # Use find command to locate chrome/headless_shell binaries
    try:
        result = subprocess.run(
            ["find", "/opt/render/.cache", "-name", "chrome", "-o", "-name", "headless_shell"],
            capture_output=True, text=True, timeout=15
        )
        find_output = result.stdout
    except Exception as e:
        find_output = str(e)

    # Also search home directory
    try:
        result2 = subprocess.run(
            ["find", "/home", "-name", "chrome", "-o", "-name", "headless_shell"],
            capture_output=True, text=True, timeout=15
        )
        find_home = result2.stdout
    except Exception as e:
        find_home = str(e)

    return {
        "cwd": os.getcwd(),
        "CHROME_PATH_env": os.environ.get("CHROME_PATH", "not set"),
        "playwright_files_sample": found[:50],
        "find_render_cache": find_output,
        "find_home": find_home,
        "get_chrome_path_result": get_chrome_path()
    }

@app.post("/solve", response_model=CookieResponse)
async def solve_cloudflare(request: SolveRequest):
    try:
        if not request.url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        cookie, final_url = get_cloudflare_cookie(
            url=request.url,
            use_cache=request.use_cache,
            timeout=request.timeout,
            debug=False
        )
        return CookieResponse(success=True, cookie=cookie, url=final_url)
    except Exception as e:
        logger.exception("POST /solve error")
        return CookieResponse(success=False, error=str(e))

@app.get("/solve", response_model=CookieResponse)
async def solve_cloudflare_get(
    url: str = Query(..., description="Target URL"),
    use_cache: bool = Query(True, description="Use browser cache"),
    timeout: int = Query(30, description="Timeout in seconds")
):
    try:
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        cookie, final_url = get_cloudflare_cookie(
            url=url,
            use_cache=use_cache,
            timeout=timeout,
            debug=False
        )
        return CookieResponse(success=True, cookie=cookie, url=final_url)
    except Exception as e:
        logger.exception("GET /solve error")
        return CookieResponse(success=False, error=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
