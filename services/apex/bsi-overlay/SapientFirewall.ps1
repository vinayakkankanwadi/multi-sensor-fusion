<#
.SYNOPSIS
  Opens Windows Firewall on the BSI Flex 335 v2 host so the Linux Apex
  middleware (on another machine) can reach the SAPIENT DataAgent
  listeners.

.DESCRIPTION
  Run as Administrator. Idempotent — re-running is a no-op.

    1. Diagnoses: firewall profile state, existing matching rules,
       listeners on SAPIENT ports.
    2. Adds two inbound Allow rules if missing:
         - "Allow ICMPv4-In (Echo Request)"   (so ping works)
         - "SAPIENT DA Inbound" on TCP
              14000 (DMM_DA), 14005-14007 (ASM_DA 1/2/3),
              12002 (HDA tasking), 12003 (GUI), 14001 (SDA client)
    3. Verifies the rules exist and are enabled.

  Does NOT disable the firewall — only adds explicit Allow rules.

.NOTES
  After this runs, from the Linux Apex host:
      ping 192.168.201.152                       # should answer
      curl -X POST http://localhost:8094/run     # regression should pass
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# ---- Must run elevated ---------------------------------------------------

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Error "Run this script from an elevated PowerShell (Run as Administrator)."
    exit 1
}

# ---- Config --------------------------------------------------------------

$IcmpRuleName = "Allow ICMPv4-In (Echo Request)"
$TcpRuleName  = "SAPIENT DA Inbound"
$Ports        = 14000, 14005, 14006, 14007, 12002, 12003, 14001
$Profiles     = "Domain","Private","Public"

# ---- 1. Diagnose ---------------------------------------------------------

Write-Host ""
Write-Host "=== Firewall profiles ===" -ForegroundColor Cyan
Get-NetFirewallProfile | Format-Table Name, Enabled

Write-Host "=== Existing SAPIENT-related inbound rules ===" -ForegroundColor Cyan
Get-NetFirewallRule -Direction Inbound -Action Allow -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -match 'Sapient|DataAgent|14005|14006|14007|14000|ICMPv4-In' } |
  Format-Table DisplayName, Enabled

Write-Host "=== Listeners on SAPIENT ports ===" -ForegroundColor Cyan
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $Ports -contains $_.LocalPort } |
  Sort-Object LocalPort |
  Format-Table LocalAddress, LocalPort, OwningProcess

# ---- 2. Apply (idempotent) -----------------------------------------------

Write-Host "=== Applying firewall rules ===" -ForegroundColor Cyan

if (Get-NetFirewallRule -DisplayName $IcmpRuleName -ErrorAction SilentlyContinue) {
    Write-Host "  '$IcmpRuleName' already exists - skipping."
} else {
    New-NetFirewallRule -DisplayName $IcmpRuleName `
        -Protocol ICMPv4 -IcmpType 8 -Direction Inbound -Action Allow `
        -Profile $Profiles | Out-Null
    Write-Host "  Created '$IcmpRuleName'" -ForegroundColor Green
}

if (Get-NetFirewallRule -DisplayName $TcpRuleName -ErrorAction SilentlyContinue) {
    Write-Host "  '$TcpRuleName' already exists - skipping."
} else {
    New-NetFirewallRule -DisplayName $TcpRuleName `
        -Direction Inbound -Protocol TCP -Action Allow `
        -LocalPort $Ports -Profile $Profiles | Out-Null
    Write-Host "  Created '$TcpRuleName' on ports: $($Ports -join ', ')" -ForegroundColor Green
}

# ---- 3. Verify -----------------------------------------------------------

Write-Host ""
Write-Host "=== Final state ===" -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName $IcmpRuleName, $TcpRuleName -ErrorAction SilentlyContinue |
  Format-Table DisplayName, Enabled, Direction, Action

Write-Host ""
Write-Host "Done. Now from the Linux Apex host run:" -ForegroundColor Green
Write-Host "  ping 192.168.201.152"
Write-Host "  curl -X POST http://localhost:8094/run"
Write-Host ""
Write-Host "To remove these rules later:" -ForegroundColor DarkGray
Write-Host "  Remove-NetFirewallRule -DisplayName `"$IcmpRuleName`",`"$TcpRuleName`""
