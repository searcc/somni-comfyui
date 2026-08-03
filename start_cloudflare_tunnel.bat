@echo off
echo Starting Permanent Cloudflare Tunnel...
"%~dp0cloudflared.exe" tunnel --url http://127.0.0.1:8080
pause