# OPA_PHONO + Raspberry Pi ADC HAT

SKiDL description of the OPA_PHONO RIAA preamp extended with a Raspberry Pi
40-pin GPIO header and a HiFiBerry-style stereo ADC, so the preamp output
can be captured digitally by the Pi.

## Block diagram

```
RCA L/R ── RIAA preamp (OPA1644 + OPA1612, ±6V) ──┐
                                                  ├── PCM1863 ADC ── I2S ── Pi 40-pin header
Pi 5V ──── LTC3265 charge pump ── ±6V ────────────┘                  I2C control
Pi 3V3 ─── ADC DVDD/AVDD, EEPROM VCC                                 ID_SD/ID_SC
                                                  24C32 HAT-ID EEPROM
```

* **Power** comes from the Pi: 5V (header pins 2/4) feeds the existing LTC3265
  charge pump for the ±6V analog rails. 3.3V (pin 1/17) powers the ADC
  digital side and the HAT EEPROM.
* **Audio** flows: RCA → preamp → AC-couple + anti-alias filter → PCM1863
  single-ended inputs (`VINL1+`/`VINR1+`).
* **I2S** master is the PCM1863 (it owns BCK/LRCK); the Pi clocks in audio
  on BCM18/19/20.
* **I2C** control of the ADC is on the primary bus (BCM2/3, header 3/5).
* **HAT-ID EEPROM** (24C32) sits on the dedicated ID bus (header 27/28),
  with 3.9k pull-ups per the HAT spec.

## Files

| File | Purpose |
| --- | --- |
| `opa_phono_pi.py` | Single-file SKiDL design: preamp, PSU, ADC, EEPROM, Pi header. |
| `requirements.txt` | Python deps. |

## Build

```bash
pip install -r requirements.txt
python opa_phono_pi.py            # runs ERC + writes opa_phono_pi.net
python opa_phono_pi.py --erc      # ERC only
```

The generated `opa_phono_pi.net` is a KiCad-compatible netlist that can be
imported into a fresh `.kicad_pcb` for layout.

## Symbol / footprint notes

The script uses standard KiCad libraries where possible:
- `Amplifier_Operational:OPA1644`, `Amplifier_Operational:OPA1612`
- `Analog_ADC:PCM1863`
- `Memory_EEPROM:24LC32`
- `Connector_Generic:Conn_02x20_Odd_Even`
- `Regulator_SwitchedCapacitor:LTC3265`

Two parts come from the project library `OPA_PHONO.pretty/`:
- `PJRAS2X1S01X` (Switchcraft RCA jack)

If your KiCad install is missing any of `LTC3265`, `PCM1863`, or `OPA1644`
symbols, install the latest KiCad symbol libraries or substitute compatible
generic symbols and update the pin name strings in `opa_phono_pi.py`.

## Linux / Pi setup notes

After flashing the EEPROM with a HAT image (see `eeptools` from the
`raspberrypi/hats` repo), the kernel auto-loads the matching device-tree
overlay. Until then, add to `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=hifiberry-dacplusadcpro   # or a custom overlay binding PCM1863
```

The PCM1863 is configured over I2C (default address `0x4A` with both ADR
pins to GND) by the overlay/driver.
