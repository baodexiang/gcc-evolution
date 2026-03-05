@echo off
echo Starting FilterChain Worker (loop mode, refresh every 4h)...
python filter_chain_worker.py --loop
pause
