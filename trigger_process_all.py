#!/usr/bin/env python3
"""Test the process-all endpoint to trigger pipeline."""

import asyncio
import httpx
import json

async def test_process_all():
    async with httpx.AsyncClient() as client:
        print("[TEST] Calling POST /api/pipeline/process-all...")
        try:
            response = await client.post(
                "http://127.0.0.1:8000/api/pipeline/process-all",
                timeout=120.0
            )
            print(f"[RESPONSE] Status: {response.status_code}")
            print(f"[RESPONSE] Body: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[RESULT] {json.dumps(data, indent=2)}")
                return True
            else:
                print(f"[ERROR] HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = asyncio.run(test_process_all())
    exit(0 if success else 1)
