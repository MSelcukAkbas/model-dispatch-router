[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SourceDir = 'C:\Users\akbas\Desktop\agentmind\skills\model-dispatch-router',
    [string]$PluginSkillsDir = 'C:\Users\akbas\.codex\plugins\cache\personal\agentmind-model-dispatch-router\0.2.0+codex.20260908221819\skills'
)

$ErrorActionPreference = 'Stop'
$skillName = 'model-dispatch-router'

function Get-TreeManifest {
    param([Parameter(Mandatory)][string]$Root)

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    Get-ChildItem -LiteralPath $rootPath -Recurse -File | ForEach-Object {
        [pscustomobject]@{
            Path = $_.FullName.Substring($rootPath.Length).TrimStart('\')
            Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } | Sort-Object Path
}

if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
    throw "Kaynak klasor bulunamadi: $SourceDir"
}

if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'SKILL.md') -PathType Leaf)) {
    throw "Kaynak klasorde SKILL.md bulunamadi: $SourceDir"
}

if (-not (Test-Path -LiteralPath $PluginSkillsDir -PathType Container)) {
    throw "Plugin skills klasoru bulunamadi: $PluginSkillsDir"
}

$sourcePath = (Resolve-Path -LiteralPath $SourceDir).Path.TrimEnd('\')
$skillsPath = (Resolve-Path -LiteralPath $PluginSkillsDir).Path.TrimEnd('\')
$targetPath = [System.IO.Path]::GetFullPath((Join-Path $skillsPath $skillName)).TrimEnd('\')
$requiredPrefix = $skillsPath + [System.IO.Path]::DirectorySeparatorChar

if (-not $targetPath.StartsWith($requiredPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Guvenlik denetimi basarisiz: hedef plugin skills klasorunun disinda: $targetPath"
}

if ([System.IO.Path]::GetFileName($targetPath) -ne $skillName) {
    throw "Guvenlik denetimi basarisiz: beklenmeyen hedef klasor adi: $targetPath"
}

if ($sourcePath.Equals($targetPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Kaynak ve hedef ayni klasor olamaz.'
}

if (-not $PSCmdlet.ShouldProcess($targetPath, "Eski skill klasorunu $sourcePath ile degistir")) {
    return
}

$operationId = [guid]::NewGuid().ToString('N')
$stagingPath = Join-Path $skillsPath ".$skillName.sync-$operationId"
$backupPath = Join-Path $skillsPath ".$skillName.backup-$operationId"
$targetMovedToBackup = $false

try {
    Copy-Item -LiteralPath $sourcePath -Destination $stagingPath -Recurse -Force

    if (-not (Test-Path -LiteralPath (Join-Path $stagingPath 'SKILL.md') -PathType Leaf)) {
        throw 'Gecici kopyada SKILL.md bulunamadi.'
    }

    $sourceManifest = @(Get-TreeManifest -Root $sourcePath)
    $stagingManifest = @(Get-TreeManifest -Root $stagingPath)
    $copyDifference = Compare-Object -ReferenceObject $sourceManifest -DifferenceObject $stagingManifest -Property Path, Hash

    if ($copyDifference) {
        throw 'Gecici kopya kaynakla ayni degil; mevcut plugin skill degistirilmedi.'
    }

    if (Test-Path -LiteralPath $targetPath) {
        $resolvedTarget = (Resolve-Path -LiteralPath $targetPath).Path.TrimEnd('\')
        if (-not $resolvedTarget.Equals($targetPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Guvenlik denetimi basarisiz: hedef beklenen dizine cozumlenmedi: $resolvedTarget"
        }

        Move-Item -LiteralPath $targetPath -Destination $backupPath
        $targetMovedToBackup = $true
    }

    try {
        Move-Item -LiteralPath $stagingPath -Destination $targetPath
    }
    catch {
        if ($targetMovedToBackup -and -not (Test-Path -LiteralPath $targetPath)) {
            Move-Item -LiteralPath $backupPath -Destination $targetPath
            $targetMovedToBackup = $false
        }
        throw
    }

    $targetManifest = @(Get-TreeManifest -Root $targetPath)
    $finalDifference = Compare-Object -ReferenceObject $sourceManifest -DifferenceObject $targetManifest -Property Path, Hash
    if ($finalDifference) {
        throw 'Son hedef kopyasi kaynakla ayni degil.'
    }

    if ($targetMovedToBackup -and (Test-Path -LiteralPath $backupPath)) {
        Remove-Item -LiteralPath $backupPath -Recurse -Force
        $targetMovedToBackup = $false
    }

    Write-Host "Skill guncellendi: $targetPath"
    Write-Host "Dogrulanan dosya sayisi: $($targetManifest.Count)"
    Write-Host 'Degisikligin yuklenmesi icin yeni bir Codex gorevi acin.'
}
finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }

    if ($targetMovedToBackup -and (Test-Path -LiteralPath $backupPath)) {
        Write-Warning "Eski skill yedegi silinmedi: $backupPath"
    }
}
