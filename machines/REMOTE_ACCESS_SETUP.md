# Setting up remote access on a Windows machine

From the setup on 30 Sep to 1 Oct 2026 and the HP on 31 Oct 2026. Do not change passwords or firewall settings on Shivam's behalf.

- **SSH server:** install OpenSSH Server through Settings, Optional features; `Add-WindowsCapability` failed in PowerShell 7. Set Wi-Fi to Private and add a firewall rule for port 22.
- **Keys:** create them with an empty passphrase. PowerShell `-N '""'` sets a literal passphrase. For an admin account the key goes in `C:\ProgramData\ssh\administrators_authorized_keys`.
- **Across networks:** use Tailscale.
- **RDP:** `mstsc` needs the Windows password, not the PIN.
- **Bitdefender:** its firewall is the registered one and is invisible to Windows Firewall checks. RDP port 3389 stayed blocked until it got an IP exception. NordVPN was not the cause.
