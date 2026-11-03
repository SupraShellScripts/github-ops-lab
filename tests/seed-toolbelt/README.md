# Public-safe PowerShell Seed Toolbelt Tests

Original synthetic test fixtures for an optional PowerShell 5.1/Core agent
bootstrap toolbelt. The module is standalone: no Git, network, secrets,
administrative privileges, external packages, dynamic code evaluation or
software installation.

The suite tests environment observation, source inventory, JSON/XML/text/
Markdown reading, literal searches, AST syntax inspection, and packaging
**untrusted** PowerShell tool candidates without executing or registering
generated code. XML DTDs and external resolution are prohibited.

The Windows PowerShell 5.1 test suite constructs Thai filename/text fixtures
from Unicode code points because Windows PowerShell 5.1 may parse unsigned
UTF-8 `.ps1` files as the machine ANSI code page. All data remains synthetic.

Do not treat syntax checking as a security sandbox. This module deliberately
does not implement independent grants, tool registration, provider egress,
signed self-modification, or runtime authority. The application using it must
supply those separate controls.

Run locally:

```powershell
powershell.exe -NoProfile -NonInteractive -File tests/seed-toolbelt/Test-SeedToolbelt.ps1
```

or under `pwsh` on Linux. Public Actions executes both.
