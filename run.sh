#!/bin/bash
echo "====================================="
echo "   帕鲁Mod管理器 - Launcher"
echo "====================================="
echo ""

# Check for Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[ERROR] Python is not installed."
    exit 1
fi

PYTHON="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON="python"
fi

# Check for virtual environment
if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    $PYTHON -m venv venv
fi

# Activate and install
source venv/bin/activate
echo "[INFO] Checking dependencies..."
pip install -r requirements.txt -q

# Run
echo "[INFO] Starting 帕鲁Mod管理器..."
echo ""
$PYTHON main.py

deactivate
