Set-Location (Split-Path $PSScriptRoot -Parent)
$exe = "C:\Temp\release_test\test_exe.exe"
Start-Process -FilePath $exe
Start-Sleep 4

function Make-Payload($id) {
    $hand = @("4m","6m","2p","5p","7p","9p","1s","2s","7s","8s","1z","3z","3z","$id")
    $payload = @{
        my_seat = 1; chang = 0; ju = 0; ben = 0; liqibang = 0
        left_tile_count = 68; tsumo_count = 5; doras = @("8p")
        scores = @(25000, 25000, 25000, 25000)
        hand = $hand
        melds = @(@(),@(),@(),@())
        reach_states = @(@{is_reach=$false;reach_turn=-1;is_ippatsu=$false},@{is_reach=$false;reach_turn=-1;is_ippatsu=$false},@{is_reach=$false;reach_turn=-1;is_ippatsu=$false},@{is_reach=$false;reach_turn=-1;is_ippatsu=$false})
        river = @(@("3z"),@(),@(),@())
    } | ConvertTo-Json -Depth 5
    return $payload
}

# 3つのリクエストを同時に発火（古い順に処理される）
$jobs = @()
for ($i = 1; $i -le 3; $i++) {
    $payload = Make-Payload "$i" + "m"
    $jobs += Start-Job -ScriptBlock {
        param($payload)
        $resp = Invoke-WebRequest "http://localhost:8080/api/evaluate" -Method POST -Body $payload -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
        return $resp.Content.Length
    } -ArgumentList $payload
}

# 全部終わるまで待つ
$results = $jobs | Wait-Job | Receive-Job
Write-Host "Response sizes: $($results -join ', ')"
Write-Host "Server should have processed 3 requests, but client should only apply the last one"
Get-Process "test_exe" -ErrorAction SilentlyContinue | Stop-Process -Force
