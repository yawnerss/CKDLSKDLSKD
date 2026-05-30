import sys
import time
import os
import shutil
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from seleniumbase import Driver
import uvicorn

CACHE_DIR = "chrome_cache"

app = FastAPI(
    title="Cloudflare Cookie Solver API",
    description="Solves Cloudflare challenges and returns cf_clearance cookies",
    version="1.0.0"
)

# Enable CORS for all origins
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
    timeout: int = 30  # Changed from 15 to 30

def get_cloudflare_cookie(url: str, use_cache: bool = True, timeout: int = 30, debug: bool = False) -> tuple:
    """
    Solve Cloudflare challenge and extract cf_clearance cookie + final URL.
    Returns tuple of (cookie_value, final_url) or raises exception on failure.
    """
    if not use_cache and os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
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
            print(f"[DEBUG] Opening URL: {url}")
        
        driver.uc_open_with_reconnect(url, reconnect_time=0.5)
        
        # Poll for cf_clearance with optimized timing
        poll_count = 0
        while time.time() - start_time < timeout:
            poll_count += 1
            
            try:
                current_title = driver.title or ""
                current_url = driver.current_url or ""
                
                if debug and poll_count % 50 == 0:
                    elapsed = time.time() - start_time
                    print(f"[DEBUG] {elapsed:.1f}s - Title: {current_title[:50]}")
                
                # Check if challenge is complete (multiple conditions)
                challenge_complete = (
                    current_title and 
                    "Just a moment" not in current_title and
                    "Challenge" not in current_title and
                    len(current_title) > 0
                )
                
                if challenge_complete:
                    cookies = driver.get_cookies()
                    
                    # Find cf_clearance cookie
                    for c in cookies:
                        if c['name'] == 'cf_clearance':
                            final_url = driver.current_url
                            if debug:
                                print(f"[DEBUG] ✅ Challenge solved in {time.time() - start_time:.1f}s")
                            return c['value'], final_url
                
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Poll error: {str(e)}")
                pass
            
            time.sleep(0.01)
        
        # Timeout - get current state for debugging
        try:
            final_title = driver.title or "No title"
            final_url = driver.current_url or "No URL"
            raise TimeoutError(
                f"Cloudflare challenge timeout after {timeout}s. "
                f"Last title: '{final_title}' | URL: {final_url}"
            )
        except:
            raise TimeoutError(f"Cloudflare challenge timeout after {timeout} seconds")
        
    except Exception as e:
        raise Exception(f"Error solving Cloudflare challenge: {str(e)}")
    finally:
        try:
            driver.quit()
        except:
            pass

@app.get("/")
async def root():
    """API documentation"""
    return {
        "message": "Cloudflare Cookie Solver API",
        "endpoints": {
            "POST /solve": "Solve CF challenge and get cookie",
            "GET /solve": "Query parameter version (url, use_cache, timeout)",
            "GET /health": "Health check"
        },
        "example": {
            "url": "https://checkton.online",
            "use_cache": True,
            "timeout": 15
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post("/solve", response_model=CookieResponse)
async def solve_cloudflare(request: SolveRequest):
    """
    POST endpoint to solve Cloudflare challenge
    
    Request body:
    {
        "url": "https://example.com",
        "use_cache": true,
        "timeout": 30
    }
    """
    try:
        if not request.url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        
        cookie, final_url = get_cloudflare_cookie(
            url=request.url,
            use_cache=request.use_cache,
            timeout=request.timeout,
            debug=False
        )
        
        return CookieResponse(
            success=True,
            cookie=cookie,
            url=final_url
        )
    
    except Exception as e:
        return CookieResponse(
            success=False,
            error=str(e)
        )

@app.get("/solve", response_model=CookieResponse)
async def solve_cloudflare_get(
    url: str = Query(..., description="Target URL"),
    use_cache: bool = Query(True, description="Use browser cache"),
    timeout: int = Query(30, description="Timeout in seconds")
):
    """
    GET endpoint to solve Cloudflare challenge
    
    Query parameters:
    - url: Target URL (required)
    - use_cache: Use browser cache (default: true)
    - timeout: Timeout in seconds (default: 30)
    
    Example: /solve?url=https://checkton.online&timeout=30
    """
    try:
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        
        cookie, final_url = get_cloudflare_cookie(
            url=url,
            use_cache=use_cache,
            timeout=timeout,
            debug=False
        )
        
        return CookieResponse(
            success=True,
            cookie=cookie,
            url=final_url
        )
    
    except Exception as e:
        return CookieResponse(
            success=False,
            error=str(e)
        )

if __name__ == "__main__":
    # Run with: python cf_api.py
    # Or specify: python cf_api.py --host 0.0.0.0 --port 8000
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )
