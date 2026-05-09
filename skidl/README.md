# OPA_PHONO + Raspberry Pi ADC HAT

SKiDL description of the OPA_PHONO RIAA preamp extended with a Raspberry Pi
40-pin GPIO header and a HiFiBerry-style stereo ADC, so the preamp output
can be captured digitally by the Pi.

**The design is fully self-contained**: every part (R, C, OPA1644, OPA1612,
LTC3265, PCM1863, 24C32, RPi 40-pin header, RCA jack) is defined inline
with explicit pin lists using SKiDL's `tool=SKIDL` backend. No external
KiCad symbol libraries are required to generate the netlist — only the
footprint names referenced in the output (standard KiCad footprint libs
plus the project's `OPA_PHONO.pretty` for the RCA jack).

## Block diagram

```
RCA L/R ── RIAA preamp (OPA1644 + OPA1612, ±6V) ──┐
                                                  ├── PCM1863 ADC ── I2S ── Pi 40-pin header
Pi 5V ──── LTC3265 charge pump ── ±6V ────────────┘                  I2C control
Pi 3V3 ─── ADC AVDD/DVDD, EEPROM VCC                                 ID_SD/ID_SC
                                                  24C32 HAT-ID EEPROM
```

* **Power**: Pi 5V (header pins 2/4) feeds the LTC3265 charge pump that
  generates the ±6V analog rails. Pi 3.3V (pin 1/17) powers the ADC
  digital side and the HAT EEPROM.
* **Audio**: RCA → preamp → AC-couple + RC anti-alias → PCM1863
  single-ended inputs (`VINL1+/VINR1+`).
* **I2S**: PCM1863 acts as master (BCK/LRCK); Pi clocks data in on
  BCM18/19/20.
* **I2C**: control of the ADC on BCM2/3 (header 3/5).
* **HAT-ID EEPROM** (24C32) on the dedicated ID bus (header 27/28),
  with the spec-mandated 3.9 k pull-ups.

## Files

| File | Purpose |
| --- | --- |
| `opa_phono_pi.py` | Single-file SKiDL design with all parts defined inline. |
| `requirements.txt` | Python deps (just `skidl`). |

## Build

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python opa_phono_pi.py            # ERC + writes opa_phono_pi.net
python opa_phono_pi.py --erc      # ERC only
```

The generated `opa_phono_pi.net` is a KiCad-compatible netlist that can
be imported into a fresh `.kicad_pcb` for layout. Expect ~321 components
and a clean ERC pass (`ERC INFO: No errors or warnings found`).

The `WARNING: KICAD_SYMBOL_DIR ... missing` and
`WARNING: fp-lib-table file was not found` lines printed by SKiDL on
import are harmless — this design does not pull symbols from those
libraries.

## Pin maps

All inline part definitions follow these pin maps:

* **OPA1644** (SOIC-14 quad): standard TI pinout (1=OUTA, 4=V+, 11=V-, …).
* **OPA1612** (SOIC-8 dual): standard TI pinout (1=OUTA, 4=V-, 8=V+, …).
* **LTC3265** (DFN-18 + EP): pin map matches the project's existing
  `OPA_PHONO:LTC3265xDHC` symbol exactly.
* **PCM1863** (TSSOP-20): per TI SLASE45 datasheet. **Verify pin numbers
  against the latest datasheet before fabrication** — the logical
  connections are correct, pin numbering may need a tweak depending on
  package variant.
* **24C32** (SOIC-8): standard I2C EEPROM pinout.
* **RPi GPIO** (2x20 header): pins numbered 1–40 per the official
  pinout; 3V3 on 1/17, 5V on 2/4, ground on 6/9/14/20/25/30/34/39,
  I2C on 3/5, I2S BCK/LRCK/DIN on 12/35/38, ID_SD/ID_SC on 27/28.
* **PJRAS2X1S01X** (Switchcraft dual RCA): pin labels `T1`/`S1`/`T2`/`S2`
  matching the local `OPA_PHONO.pretty/PJRAS2X1S01X.kicad_mod` footprint.

## Linux / Pi setup notes

After flashing the EEPROM with a HAT image (see `eeptools` from the
`raspberrypi/hats` repo), the kernel auto-loads the matching device-tree
overlay. Until then, add to `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=hifiberry-dacplusadcpro   # or a custom overlay binding PCM1863
```

The PCM1863 is configured over I2C (default address `0x4A` with `MD`
strapped to GND) by the overlay/driver.
