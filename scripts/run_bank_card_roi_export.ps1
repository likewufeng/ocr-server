param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$toolsDir = Join-Path $ProjectRoot ".tools"
$wheelDir = Join-Path $toolsDir "onnx-wheels"
$venvDir = Join-Path $toolsDir "onnx-export-venv"
$statusFile = Join-Path $toolsDir "bank-card-roi-export-status.txt"
$modelFile = Join-Path $ProjectRoot "models\bank_card_roi\yolo_best.onnx"
$weightsFile = "D:\web\self\study\dataset\CreditCard-OCR\models\yolo_best.pt"
$buildWeightsFile = Join-Path $toolsDir "roi-build\yolo_best.pt"
$datasetRoot = "D:\web\self\study\dataset\CreditCard-OCR\dataset for detection\detection"
$reportFile = Join-Path $ProjectRoot "reports\bank_card_roi_test"

function Set-Status([string]$message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $message" | Tee-Object -FilePath $statusFile -Append
}

function Download-File([string]$url, [string]$destination) {
    if ((Test-Path -LiteralPath $destination) -and ((Get-Item $destination).Length -gt 0)) {
        Set-Status "Resuming download: $destination"
        & curl.exe --noproxy "*" -L --fail --retry 20 --retry-delay 15 --continue-at - --output $destination $url
    }
    else {
        Set-Status "Starting download: $destination"
        & curl.exe --noproxy "*" -L --fail --retry 20 --retry-delay 15 --output $destination $url
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed: $url"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $modelFile) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $buildWeightsFile) | Out-Null
    if (-not (Test-Path -LiteralPath $weightsFile)) {
        throw "Training weights do not exist: $weightsFile"
    }
    Copy-Item -LiteralPath $weightsFile -Destination $buildWeightsFile -Force
    Set-Content -Path $statusFile -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') started"

    $torchWheel = Join-Path $wheelDir "torch-2.4.1+cpu-cp39-cp39-win_amd64.whl"
    $visionWheel = Join-Path $wheelDir "torchvision-0.19.1+cpu-cp39-cp39-win_amd64.whl"
    Download-File "https://download.pytorch.org/whl/cpu/torch-2.4.1%2Bcpu-cp39-cp39-win_amd64.whl" $torchWheel
    Download-File "https://download.pytorch.org/whl/cpu/torchvision-0.19.1%2Bcpu-cp39-cp39-win_amd64.whl" $visionWheel

    $basePython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $basePython)) {
        throw "Project Python does not exist: $basePython"
    }
    if (-not (Test-Path (Join-Path $venvDir "Scripts\python.exe"))) {
        Set-Status "Creating isolated export environment"
        & $basePython -m venv --system-site-packages $venvDir
    }
    $python = Join-Path $venvDir "Scripts\python.exe"
    Set-Status "Installing local CPU torch wheels"
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
    & $python -m pip install $torchWheel $visionWheel
    if ($LASTEXITCODE -ne 0) { throw "torch wheel installation failed with exit code $LASTEXITCODE" }
    Set-Status "Installing ONNX export tools"
    & $python -m pip install --index-url https://pypi.org/simple --timeout 120 --retries 10 `
        "ultralytics==8.3.0" "onnx==1.16.2" "onnxslim==0.1.95"
    if ($LASTEXITCODE -ne 0) { throw "ONNX export tool installation failed with exit code $LASTEXITCODE" }

    Set-Status "Exporting bank-card ROI ONNX model"
    & $python (Join-Path $ProjectRoot "scripts\export_bank_card_roi_onnx.py") `
        --weights $buildWeightsFile --output $modelFile --simplify
    if ($LASTEXITCODE -ne 0) { throw "ONNX model export failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $modelFile)) {
        throw "ONNX export did not create: $modelFile"
    }

    Set-Status "Evaluating ROI detector against independent test split"
    & $python (Join-Path $ProjectRoot "scripts\evaluate_bank_card_roi_detection.py") `
        --model $modelFile --dataset $datasetRoot --split test --output $reportFile
    if ($LASTEXITCODE -ne 0) { throw "ROI detector evaluation failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path ($reportFile + ".md"))) {
        throw "ROI detector evaluation did not create: $($reportFile + '.md')"
    }
    Set-Status "SUCCESS model=$modelFile report=$($reportFile + '.md')"
}
catch {
    Set-Status "FAILED $($_.Exception.Message)"
    exit 1
}
