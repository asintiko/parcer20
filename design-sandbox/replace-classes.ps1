Get-ChildItem -Path "src" -Recurse -Include *.tsx,*.ts,*.css | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    $content = $content -replace 'text-text-inverse', 'text-foreground-inverse'
    $content = $content -replace 'text-text-secondary', 'text-foreground-secondary'
    $content = $content -replace 'text-text-muted', 'text-foreground-muted'
    $content = $content -replace '\btext-text\b', 'text-foreground'
    Set-Content -Path $_.FullName -Value $content -NoNewline
}
Write-Host "Replacement complete!"
