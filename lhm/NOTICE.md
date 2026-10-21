# Bundled third-party binaries

The DLLs in this folder are **unmodified** binaries from
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
**v0.9.6** (commit `3d331e3370efb858411f19511373eff65a218701`). Only the files
needed to read CPU sensors are included; the GUI, plotting libraries and
translations were removed to keep the repository small.

| Component | License | Source |
| --- | --- | --- |
| LibreHardwareMonitor (`LibreHardwareMonitorLib.dll`, `BlackSharp.Core.dll`, `DiskInfoToolkit.dll`, `RAMSPDToolkit-NDD.dll`) | MPL-2.0 | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| HidSharp (`HidSharp.dll`) | Apache-2.0 | https://github.com/IntergatedCircuits/HidSharp |
| .NET support libraries (`System.Buffers.dll`, `System.Memory.dll`, `System.Numerics.Vectors.dll`, `System.Runtime.CompilerServices.Unsafe.dll`) | MIT | https://github.com/dotnet/runtime |

The full MPL-2.0 text is in [`LICENSE`](LICENSE).

Source code for the MPL-2.0 components is available at the URL above. If you
prefer not to use the bundled binaries, delete this folder and run
`setup.ps1`; it downloads the current LibreHardwareMonitor release instead.
