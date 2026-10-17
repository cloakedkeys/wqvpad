# wqvpad

Download photos from **Casio WQV wrist cameras** (WQV-1, WQV-2, WQV-3, WQV-10) on **Windows 11**, macOS and Linux, using Casio's original **PAD infrared adapters**. No Windows XP virtual machine, no Palm, and no Casio drivers needed.

> **Status: early, not yet tested on real hardware.** Both watch protocols are ported from projects proven on real watches, and every step is tested against simulated watches built from recorded conversations. The adapter code follows the chip documentation. A real watch and adapter are the final test. If you try it, please report what happened (see [Reporting a problem](#reporting-a-problem)).

## Quick start

1. **Get wqvpad.** On Windows, download `wqvpad.exe` from the [Releases page](https://github.com/cloakedkeys/wqvpad/releases). Elsewhere, see [Install](#install).
2. **Connect your adapter.** Plug in the PAD-5, or plug the PAD-1/PAD-2/PAD-2B into a USB-to-serial adapter.
3. **Find it** (serial adapters only): open a Command Prompt where `wqvpad.exe` is and run

   ```
   wqvpad list
   ```

   and note the COM port, for example `COM3`.
4. **Start the download:**

   ```
   wqvpad download --adapter pad5
   wqvpad download --adapter pad2b --port COM3
   ```

   (Use `pad1`, `pad2` or `pad2b` to match your adapter.) With a PAD-5 on Windows, the first run offers to set up its driver; see [why it asks for permission](#pad-5-usb).
5. **On the watch:** IR Mode, Communication Menu, **PC**, press **F**. The watch shows **REMOTE**. Hold it 5-10 cm from the adapter, facing it, within 60 seconds.
6. **Wait.** wqvpad finds the watch, works out the model and downloads every photo. They land in a `wqv_photos` folder next to where you ran it (`--out FOLDER` to choose another).
7. **Something went wrong?** Run the same command again with `--capture log.txt` added and [send us the log](#reporting-a-problem).

## Supported hardware

| Adapter | Connection | How wqvpad talks to it |
|---|---|---|
| **PAD-5** | USB | Drives its SigmaTel STIr4200 chip directly through libusb. On Windows, wqvpad installs the driver it needs the first time (below). |
| **PAD-2 / PAD-2B** | 9-pin serial | A rebadged Extended Systems JetEye ESI-9680 pod. Works as a normal COM port through any USB-to-serial adapter. |
| **PAD-1** | 9-pin serial | An OEM Parallax LiteLink pod (HP HSDL-7001 chip, shipped with the PC-Unite HBX-100). Works as a COM port. wqvpad resets it to 115,200 baud with an RTS pulse at startup. It is powered from the serial control lines, so a weak USB-serial adapter may not power it. |
| Other serial IrDA pods | 9-pin serial or TTL | Any "dumb" pod that passes bytes through may work with `--adapter serial`, for example a Locus Engineering IR module on a 5 V TTL-serial adapter with its BR pin held high for 115,200 ([wiring guide](https://chrismcovell.com/WQVLink_Connection_Help/)). Never connect TTL modules to a real RS-232 port. |

| Watch | What you get |
|---|---|
| WQV-1, WQV-2 (black and white) | PNG pictures, 120 by 120 pixels in shades of grey. |
| WQV-3, WQV-10 (colour) | JPEG pictures. |

Each picture is named after the date it was taken, then a number, then its title if you gave it one on the watch:

```
WQV_20010714_01 PARK.jpg
WQV_20010714_02.jpg
WQV_20010715_01 MY CAT.png
```

So files sort in the order the photos were taken. Characters Windows does not allow in file names (such as `?` `*` `/` `:`) are replaced with `-`. The date and title are also stored inside each picture, so they are not lost if you rename the file, and the file's own date is set to when the photo was taken.

Casio's own software never supported the PAD-5 with the WQV-1/2. wqvpad builds every frame itself, so in principle any adapter can talk to any watch, but this combination has never been tried.

## Install

**Windows, no Python needed:** download `wqvpad.exe` from the [Releases page](https://github.com/cloakedkeys/wqvpad/releases) and run it from a Command Prompt.

**Any system with Python 3.9 or newer:**

```
pip install git+https://github.com/cloakedkeys/wqvpad
```

(If you have downloaded the code yourself, `pip install .` inside its folder does the same.) On Windows this also installs `libusb-package`, which bundles the libusb DLL the PAD-5 needs.

Check the install without any hardware by downloading from a simulated watch:

```
wqvpad demo --model 10
wqvpad demo --model 1
```

## Setting up the adapter

### PAD-5 (USB)

**Windows: nothing to set up in advance.** Plug in the PAD-5 and run the download command (see [Downloading](#downloading)). The first time, wqvpad notices the PAD-5 has no driver, explains what it is about to do, and asks:

```
Install the PAD-5 driver now? [Y/n]
```

Press Enter, then click **Yes** when Windows asks for permission. The download then carries on by itself. This happens only once per PC. (To do the driver step on its own, run `wqvpad install-driver`.)

**Why Windows asks for administrator permission**

Windows only lets administrators install drivers, for any device. Casio's own PAD-5 driver is from the Windows 98-XP era and cannot run on Windows 11, so wqvpad sets up a replacement once:

* It uses **WinUSB**, a driver Microsoft already ships with Windows, and assigns it **only to the Casio PAD-5** (USB ID 066F:4200). No other device is touched.
* It creates a small certificate on your PC so Windows accepts this one driver setup file. This is the same method used by Zadig, the widely used tool for this job.
* Nothing is downloaded, nothing keeps running afterwards, and wqvpad itself never needs administrator rights again.

To undo it: open **Device Manager**, right-click the PAD-5, choose **Uninstall device** and tick **Delete the driver software**.

The installer is `wdi-simple` from Pete Batard's [libwdi](https://github.com/pbatard/libwdi) (the engine behind Zadig), included in `wqvpad.exe`. If you installed wqvpad with pip instead of using `wqvpad.exe`, use [Zadig](https://zadig.akeo.ie/): **Options → List All Devices**, pick USB ID **066F 4200**, choose **WinUSB**, click **Install Driver**.

**Linux:** give your user access to the device (a udev rule for `066f:4200`) or run with sudo. **macOS:** install libusb with Homebrew. No driver step is needed on either.

### PAD-1 / PAD-2 / PAD-2B (serial)

1. Connect the pod to a USB-to-serial adapter. Adapters with a real FTDI chip work best.
2. Run `wqvpad list` to find its COM port.
3. Recommended for FTDI adapters: in Device Manager, open the port's **Port Settings → Advanced** and set **Latency Timer** to **1 ms**. Casio warned that USB-serial adapters can be unreliable with the PAD-2B, and slow buffering is the usual cause.

A PAD-2 through a USB-to-RS-232 adapter at 115,200 baud has been confirmed working with Casio's own WQV Link on modern Windows ([Chris Covell's guide](https://chrismcovell.com/WQVLink_Connection_Help/)). That guide also advises connecting the PAD-2 only while you use it: its author suspects leaving one attached while the PC slept damaged it.

wqvpad holds DTR and RTS high. That powers the pod and, on the JetEye-based PAD-2/2B, selects 115,200 baud, the speed every WQV watch uses.

**PAD-1 power:** its label asks for ±12 V at 10 mA from the serial lines, more than many USB-serial adapters supply. One owner has run a PAD-1 on Windows 11 through a **DriverGenius USB232A-E-C** (USB-C) adapter ([WatchUSeek thread](https://www.watchuseek.com/threads/casio-hbx-100-running-a-90s-smartwatch-with-a-modern-pc.5561634/)). If the pod stays silent, try a different adapter before anything else.

## Downloading

```
wqvpad download --adapter pad5 --out photos
wqvpad download --adapter pad2b --port COM3 --out photos
```

Then, within 60 seconds, point the watch at the adapter from about 5-10 cm away and start the transfer:

* Enter **IR Mode**, open the **Communication Menu**, move the pointer to **PC** and press **F**. The watch shows **REMOTE** while it waits. (These are the steps from Casio's WQV Link manual. The WQV-3/10 also need **REMOTE**.)
* When it is done, press **A** to go back to the Communication Menu or **D** for timekeeping.

wqvpad detects the model automatically. Add `--model 1|2|3|10` to skip detection.

Useful options:

| Option | Purpose |
|---|---|
| `--trace` | Show the conversation with the watch on screen (photos and titles removed) |
| `--capture log.txt` | Save a privacy-safe log for bug reports (photos and titles removed) |
| `--keep-raw` | Also save the raw data from the watch |
| `--gap MS` | Pause before each reply (default 10 ms). Raise it if the watch shows "error" mid-transfer |
| `--wait S` | How long to wait for the watch (default 60 s) |
| `--rx-slow` | PAD-5: use the chip's slow receive line, if the PAD-5 transmits but never hears the watch |
| `--rx-sensitivity N`, `--tx-power N` | PAD-5 receiver and transmitter tuning |
| `--no-dtr`, `--no-rts` | Serial: change the control lines if a pod behaves oddly |
| `--yes` | PAD-5 on Windows: install the driver without asking first |

`wqvpad convert wqv12_dump.bin` turns a saved WQV-1/2 raw dump into PNGs again.

## Troubleshooting

* **Nothing happens:** check the watch battery (it will not enter IR mode when low), the IR mode, and the distance and angle. Hold it 5-10 cm away, facing the adapter.
* **Transfer stops part way:** fluorescent lights, sunlight and TV remotes interfere with infrared. Try `--gap 25`.
* **PAD-5 not found:** unplug it and plug it back in, then run `wqvpad install-driver` again.
* **Serial pod silent:** try another USB-serial adapter (the PAD-1 especially needs line power), or a real serial port.

## Reporting a problem

Nobody has tested wqvpad with every watch and adapter yet, so reports help a lot, including "it worked!".

1. Run your download command again with `--capture log.txt` on the end, for example:

   ```
   wqvpad download --adapter pad5 --capture log.txt
   ```

2. [Open an issue](https://github.com/cloakedkeys/wqvpad/issues/new) and attach `log.txt`. Please also say which watch, adapter and USB-serial adapter (if any) you used, what the watch showed, and what wqvpad printed.

**What the log contains, and what it does not.** It records the conversation between wqvpad and the watch: timings, connection steps, commands and acknowledgements, plus your operating system, Python version and the options you used. Your **photos and photo titles are removed** before anything is written: each piece of photo data is replaced by a note such as `[1200 bytes of photo data removed]`. It contains no file paths, user names or computer names. It is a plain text file, so you can open it and check before sharing. `--trace` shows the same privacy-safe view on screen while it runs.

## How it works

Every WQV watch frames its data the same way: `C0 [address] [control] [data] [check] C1`, with C0, C1 and 7D escaped. The families differ in the check:

* **WQV-1/2** use a plain 16-bit sum. That is not valid IrDA, so standard IrDA drivers and smart dongles throw every frame away. This is why so many people could never get these watches to talk to a PC.
* **WQV-3/10** use the standard IrDA CRC, on top of IrDA connection handling and Casio's own commands for listing and sending files.

wqvpad treats every adapter as a "dumb" light modem and does all the framing itself. The PAD-2/2B and PAD-1 already work that way. The PAD-5's STIr4200 chip does too in its slow (SIR) mode, once its registers are set up, which wqvpad does directly over USB.

## Credits

This project stands on others' reverse engineering:

* **Marcus Gröber**: the WQV-1 protocol ([mgroeber.de/wqvprot.html](https://mgroeber.de/wqvprot.html))
* **Roger Braunstein (partlyhuman)**: [wqv-blink](https://github.com/partlyhuman/wqv-blink), whose WQV-1/2 and WQV-3/10 firmware (MIT licence) the protocol modules here are ported from step by step. If you would rather have a ready-made device, his works with every model and is sold on his Ko-Fi shop.
* **Kees Jongenburger**: WQV-2 protocol notes
* **Pete Batard**: [libwdi](https://github.com/pbatard/libwdi), whose `wdi-simple` installs the PAD-5 driver
* **Stephen Hemminger and the Linux IrDA project**: the STIr4200 register documentation in the Linux `stir4200` driver (facts only; wqvpad's implementation is independent)
* **Andrew Gregory**: IrTran-P research showing the WQV-3 talks standard IrDA

Casio, PAD-5, WQV and WQV Link are trademarks of Casio Computer Co., Ltd. This project is not affiliated with Casio.

## Licence

MIT. See [LICENSE](LICENSE), which also carries the wqv-blink copyright notice for the ported code. The Windows build also includes libwdi's `wdi-simple` (LGPL v3), see [third_party/libwdi](third_party/libwdi/README.md).
