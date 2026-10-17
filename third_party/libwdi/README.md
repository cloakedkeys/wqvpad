# libwdi / wdi-simple

The Windows build of wqvpad (`wqvpad.exe`) includes `wdi-simple.exe`, the
command-line driver installer from **libwdi** by Pete Batard (the author of
Zadig). wqvpad uses it only to install Microsoft's WinUSB driver for the
Casio PAD-5 (USB ID 066F:4200).

* Licence: GNU LGPL v3 (`COPYING.LGPL-3.0.txt`, which builds on the GNU GPL v3 in `COPYING.GPL-3.0.txt`)
* Source: https://github.com/pbatard/libwdi, tag `v1.5.1`, built unmodified by
  this project's CI (`.github/workflows/ci.yml`, job `wdi-simple`) with WinUSB
  support only.
* The WinUSB driver files it carries are Microsoft's redistributable files from
  the Windows Driver Kit 8.0.

wqvpad's own code is MIT licensed and runs `wdi-simple.exe` as a separate program.
