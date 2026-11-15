$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$attach = Join-Path $root "corpus\attachments"
$textDir = Join-Path $root "corpus\_text"
New-Item -ItemType Directory -Force -Path $textDir | Out-Null

$word = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.Options.ConfirmConversions = $false
    Write-Host "[word] started"

    Get-ChildItem $attach -Filter *.doc -File | ForEach-Object {
        $docx = [IO.Path]::ChangeExtension($_.FullName, ".docx")
        if (Test-Path $docx) { Write-Host ("[skip] " + $_.Name); return }
        try {
            Write-Host ("[open] " + $_.Name)
            $d = $word.Documents.Open($_.FullName, $false, $true, $false)
            Write-Host ("[stats] tables=" + $d.Tables.Count + " paragraphs=" + $d.Paragraphs.Count)
            $d.SaveAs2($docx, 16)
            $d.Close(0)
            Write-Host ("[ok] " + [IO.Path]::GetFileName($docx))
        }
        catch {
            Write-Host ("[fail] " + $_.Name + " :: " + $_.Exception.Message)
        }
    }

    Get-ChildItem $attach -Filter *.pdf -File | ForEach-Object {
        $out = Join-Path $textDir ($_.BaseName + ".txt")
        if (Test-Path $out) { Write-Host ("[skip] " + $_.Name); return }
        try {
            Write-Host ("[pdf] " + $_.Name)
            $d = $word.Documents.Open($_.FullName, $false, $true, $false)
            $d.SaveAs2($out, 7)
            $d.Close(0)
            Write-Host ("[ok] " + [IO.Path]::GetFileName($out))
        }
        catch {
            Write-Host ("[fail] " + $_.Name + " :: " + $_.Exception.Message)
        }
    }
}
catch {
    Write-Host ("[fatal] " + $_.Exception.Message)
}
finally {
    if ($word) {
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    Write-Host "[done]"
}
