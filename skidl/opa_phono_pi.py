"""
OPA_PHONO + Raspberry Pi HAT (ADC) - self-contained SKiDL design.

All parts are defined inline using SKiDL's tool=SKIDL backend, so this
script does not require any external KiCad symbol libraries (the
KICAD_SYMBOL_DIR warnings on import are harmless). Only standard
KiCad *footprint* libraries are referenced by name in the generated
netlist for PCB layout.

Combines the existing OPA1612/OPA1644 RIAA phono preamp with a PCM1863
stereo ADC (HiFiBerry-style) on a Raspberry Pi 40-pin GPIO header.

Power flow:
    Pi 5V (header pin 2/4) -> LTC3265 charge pump -> +-6V analog rails
    Pi 3.3V (header pin 1)  -> ADC DVDD/AVDD, EEPROM VCC

Audio flow:
    RCA L/R -> RIAA preamp -> AC-couple/AA filter -> PCM1863 single-ended
    PCM1863 I2S out -> Pi I2S (BCK/LRCK/DIN)
    PCM1863 control via I2C0 on BCM2/BCM3
    HAT ID EEPROM (24C32) on ID_SD/ID_SC (BCM0/BCM1)

Run:
    python opa_phono_pi.py            # ERC + writes opa_phono_pi.net
    python opa_phono_pi.py --erc      # ERC only

NB: PCM1863 pin numbers below follow the TSSOP-20 (DBT) package; verify
against the latest TI datasheet (SLASE45) before fabrication.
"""

import logging

import skidl
from skidl import (
    Part, Pin, Net, SKIDL, TEMPLATE, generate_netlist, ERC, subcircuit, POWER,
)

# Silence the per-instance "Missing tag / Random tag generated" warnings so
# the script output stays readable. Real ERC errors still surface.
class _DropTagWarnings(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "tag" not in msg.lower()


for _lg in (skidl.logger.active_logger, skidl.logger.rt_logger):
    _lg.addFilter(_DropTagWarnings())

PIN = Pin.types  # short alias


# =============================================================================
# Manufacturer / MPN database
#
# Keys: (template_name, value).  Values: (Manufacturer, MPN).
# Sources:
#   * Existing PCB/OPA_PHONO.bom.csv for parts that were already on the
#     board (resistors, op-amps, LTC3265, RCA jack, large caps).
#   * Reasonable picks for new parts: PCM1863, 24C32, Pi header, and
#     filter/decoupling values not in the original BOM.
# Edit freely - the BOM CSV generator (bom.py) just transcribes whatever
# is here.
# =============================================================================

PART_DB = {
    # Resistors - YAGEO 0402, 1%
    ("R", "47k"):    ("YAGEO", "RT0402FRE0747KL"),     # existing BOM
    ("R", "16k"):    ("YAGEO", "RT0402FRE0716KL"),     # existing BOM
    ("R", "2.32k"):  ("YAGEO", "RT0402FRE072K32L"),    # existing BOM
    ("R", "499R"):   ("YAGEO", "RT0402FRE07499RL"),    # existing BOM
    ("R", "20.5k"):  ("YAGEO", "RC0402FR-0720K5L"),    # existing BOM
    ("R", "5.1k"):   ("YAGEO", "RC0402FR-075K1L"),     # existing BOM
    ("R", "3.3k"):   ("YAGEO", "RC0402FR-073K3L"),     # ADC AA filter
    ("R", "22k"):    ("YAGEO", "RC0402FR-0722KL"),     # ADC bias
    ("R", "4.7k"):   ("YAGEO", "RC0402FR-074K7L"),     # I2C pull-up
    ("R", "3.9k"):   ("YAGEO", "RC0402FR-073K9L"),     # HAT-ID pull-up

    # Capacitors
    ("C0402", "1u"):    ("Murata",    "GRM155R61E105KA12D"),  # existing BOM
    ("C0402", "100n"):  ("Murata",    "GRM155R71H104KE14D"),  # decoupling
    ("C0402", "470p"):  ("Murata",    "GRM1555C1H471JA01D"),  # AA filter
    ("C0402", "NP"):    ("",          ""),                    # do not populate
    ("C0805", "10u"):   ("Murata",    "GRM21BR61C106KE15L"),  # existing BOM
    ("C0805", "2.2u"):  ("Murata",    "GRM219R71C225KE15D"),  # AC-couple to ADC
    ("C1206", "47n"):   ("Panasonic", "ECH-U1C473GX5"),       # existing BOM (RIAA)
    ("C1210", "68n"):   ("Panasonic", "ECH-U1C683GX5"),       # existing BOM (RIAA)

    # ICs
    ("OPA1644", None):     ("Texas Instruments", "OPA1644AID"),         # existing BOM
    ("OPA1612", None):     ("Texas Instruments", "OPA1612AID"),         # existing BOM
    ("LTC3265", None):     ("Analog Devices",    "LTC3265EDHC#TRPBF"),  # existing BOM
    ("PCM1863", None):     ("Texas Instruments", "PCM1863DBTR"),
    ("24C32",   None):     ("Microchip",         "24LC32AT-I/SN"),

    # Connectors / mechanical
    ("RPi_Header",    None): ("Wurth Elektronik", "61304021121"),
    ("PJRAS2X1S01X",  None): ("Switchcraft",      "PJRAS2X1S01X"),     # existing BOM
}


def _attach_db(part, key, value):
    """Look up (Manufacturer, MPN) for (key, value) and attach as part fields.

    Fields must go into part.fields[...] (not plain attributes) for SKiDL to
    emit them as (field name "MPN" "...") entries in the generated netlist.
    """
    mfr, mpn = PART_DB.get((key, value), ("", ""))
    if mfr:
        part.fields["Manufacturer"] = mfr
    if mpn:
        part.fields["MPN"] = mpn
    return part


# =============================================================================
# Inline part library (templates) and value-aware constructors
# =============================================================================

_R = Part(
    name="R", ref_prefix="R", tool=SKIDL, dest=TEMPLATE,
    footprint="Resistor_SMD:R_0402_1005Metric",
    pins=[
        Pin(num=1, name="~", func=PIN.PASSIVE),
        Pin(num=2, name="~", func=PIN.PASSIVE),
    ],
)

_C0402 = Part(
    name="C", ref_prefix="C", tool=SKIDL, dest=TEMPLATE,
    footprint="Capacitor_SMD:C_0402_1005Metric",
    pins=[
        Pin(num=1, name="~", func=PIN.PASSIVE),
        Pin(num=2, name="~", func=PIN.PASSIVE),
    ],
)

_C0805 = Part(
    name="C", ref_prefix="C", tool=SKIDL, dest=TEMPLATE,
    footprint="Capacitor_SMD:C_0805_2012Metric",
    pins=[
        Pin(num=1, name="~", func=PIN.PASSIVE),
        Pin(num=2, name="~", func=PIN.PASSIVE),
    ],
)

_C1206 = Part(
    name="C", ref_prefix="C", tool=SKIDL, dest=TEMPLATE,
    footprint="Capacitor_SMD:C_1206_3216Metric",
    pins=[
        Pin(num=1, name="~", func=PIN.PASSIVE),
        Pin(num=2, name="~", func=PIN.PASSIVE),
    ],
)

_C1210 = Part(
    name="C", ref_prefix="C", tool=SKIDL, dest=TEMPLATE,
    footprint="Capacitor_SMD:C_1210_3225Metric",
    pins=[
        Pin(num=1, name="~", func=PIN.PASSIVE),
        Pin(num=2, name="~", func=PIN.PASSIVE),
    ],
)


def R(value, **kw):
    return _attach_db(_R(value=value, **kw), "R", value)


def C(value, **kw):
    return _attach_db(_C0402(value=value, **kw), "C0402", value)


def C0805(value, **kw):
    return _attach_db(_C0805(value=value, **kw), "C0805", value)


def C1206(value, **kw):
    return _attach_db(_C1206(value=value, **kw), "C1206", value)


def C1210(value, **kw):
    return _attach_db(_C1210(value=value, **kw), "C1210", value)


# OPA1644 - quad SoundPlus op-amp, SOIC-14
_OPA1644 = Part(
    name="OPA1644", ref_prefix="U", tool=SKIDL, dest=TEMPLATE,
    value="OPA1644AID",
    footprint="Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    pins=[
        Pin(num=1,  name="OUTA", func=PIN.OUTPUT),
        Pin(num=2,  name="-INA", func=PIN.INPUT),
        Pin(num=3,  name="+INA", func=PIN.INPUT),
        Pin(num=4,  name="V+",   func=PIN.PWRIN),
        Pin(num=5,  name="+INB", func=PIN.INPUT),
        Pin(num=6,  name="-INB", func=PIN.INPUT),
        Pin(num=7,  name="OUTB", func=PIN.OUTPUT),
        Pin(num=8,  name="OUTC", func=PIN.OUTPUT),
        Pin(num=9,  name="-INC", func=PIN.INPUT),
        Pin(num=10, name="+INC", func=PIN.INPUT),
        Pin(num=11, name="V-",   func=PIN.PWRIN),
        Pin(num=12, name="+IND", func=PIN.INPUT),
        Pin(num=13, name="-IND", func=PIN.INPUT),
        Pin(num=14, name="OUTD", func=PIN.OUTPUT),
    ],
)


def OPA1644():
    return _attach_db(_OPA1644(), "OPA1644", None)


# OPA1612 - dual SoundPlus op-amp, SOIC-8
_OPA1612 = Part(
    name="OPA1612", ref_prefix="U", tool=SKIDL, dest=TEMPLATE,
    value="OPA1612AID",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins=[
        Pin(num=1, name="OUTA", func=PIN.OUTPUT),
        Pin(num=2, name="-INA", func=PIN.INPUT),
        Pin(num=3, name="+INA", func=PIN.INPUT),
        Pin(num=4, name="V-",   func=PIN.PWRIN),
        Pin(num=5, name="+INB", func=PIN.INPUT),
        Pin(num=6, name="-INB", func=PIN.INPUT),
        Pin(num=7, name="OUTB", func=PIN.OUTPUT),
        Pin(num=8, name="V+",   func=PIN.PWRIN),
    ],
)


def OPA1612():
    return _attach_db(_OPA1612(), "OPA1612", None)


# LTC3265 - low noise +-V supply with boost & inverting charge pumps
# Pin map matches the project library OPA_PHONO:LTC3265xDHC.
_LTC3265 = Part(
    name="LTC3265", ref_prefix="U", tool=SKIDL, dest=TEMPLATE,
    value="LTC3265EDHC",
    footprint="Package_DFN_QFN:DFN-18-1EP_3x5mm_P0.5mm_EP1.66x4.4mm",
    pins=[
        Pin(num=1,  name="CBSTN", func=PIN.PASSIVE),
        Pin(num=2,  name="CBSTP", func=PIN.PASSIVE),
        Pin(num=3,  name="VINP",  func=PIN.PWRIN),
        Pin(num=4,  name="ENN",   func=PIN.INPUT),
        Pin(num=5,  name="BYPN",  func=PIN.PASSIVE),
        Pin(num=6,  name="ADJN",  func=PIN.INPUT),
        Pin(num=7,  name="LDON",  func=PIN.PWROUT),
        Pin(num=8,  name="VOUTN", func=PIN.PWROUT),
        Pin(num=9,  name="CINVN", func=PIN.PASSIVE),
        Pin(num=10, name="CINVP", func=PIN.PASSIVE),
        Pin(num=11, name="VINN",  func=PIN.PWRIN),
        Pin(num=12, name="RT",    func=PIN.INPUT),
        Pin(num=13, name="ENP",   func=PIN.INPUT),
        Pin(num=14, name="MODE",  func=PIN.INPUT),
        Pin(num=15, name="BYPP",  func=PIN.PASSIVE),
        Pin(num=16, name="ADJP",  func=PIN.INPUT),
        Pin(num=17, name="LDOP",  func=PIN.PWROUT),
        Pin(num=18, name="VOUTP", func=PIN.PWROUT),
        Pin(num=19, name="GND",   func=PIN.PWRIN),  # exposed pad
    ],
)


def LTC3265():
    return _attach_db(_LTC3265(), "LTC3265", None)


# PCM1863 - stereo audio ADC, TSSOP-20 (DBT package)
# Pin numbers per TI SLASE45 datasheet; verify before fabrication.
_PCM1863 = Part(
    name="PCM1863", ref_prefix="U", tool=SKIDL, dest=TEMPLATE,
    value="PCM1863DBT",
    footprint="Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    pins=[
        Pin(num=1,  name="VINL2",    func=PIN.INPUT),
        Pin(num=2,  name="VINL1+",   func=PIN.INPUT),
        Pin(num=3,  name="VINL1-",   func=PIN.INPUT),
        Pin(num=4,  name="AGND",     func=PIN.PWRIN),
        Pin(num=5,  name="VINR1-",   func=PIN.INPUT),
        Pin(num=6,  name="VINR1+",   func=PIN.INPUT),
        Pin(num=7,  name="VINR2",    func=PIN.INPUT),
        Pin(num=8,  name="REF_FILT", func=PIN.PASSIVE),
        Pin(num=9,  name="AVDD",     func=PIN.PWRIN),
        Pin(num=10, name="DVDD",     func=PIN.PWRIN),
        Pin(num=11, name="BCK",      func=PIN.OUTPUT),
        Pin(num=12, name="LRCK",     func=PIN.OUTPUT),
        Pin(num=13, name="DOUT",     func=PIN.OUTPUT),
        Pin(num=14, name="SCK",      func=PIN.INPUT),
        Pin(num=15, name="MD",       func=PIN.INPUT),
        Pin(num=16, name="MS",       func=PIN.INPUT),
        Pin(num=17, name="GPIO3",    func=PIN.BIDIR),
        Pin(num=18, name="SCL",      func=PIN.INPUT),
        Pin(num=19, name="SDA",      func=PIN.BIDIR),
        Pin(num=20, name="DGND",     func=PIN.PWRIN),
    ],
)


def PCM1863():
    return _attach_db(_PCM1863(), "PCM1863", None)


# 24C32 / 24LC32 - 32 kbit I2C EEPROM, SOIC-8
_EEPROM_24C32 = Part(
    name="24C32", ref_prefix="U", tool=SKIDL, dest=TEMPLATE,
    value="24C32",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins=[
        Pin(num=1, name="A0",  func=PIN.INPUT),
        Pin(num=2, name="A1",  func=PIN.INPUT),
        Pin(num=3, name="A2",  func=PIN.INPUT),
        Pin(num=4, name="VSS", func=PIN.PWRIN),
        Pin(num=5, name="SDA", func=PIN.BIDIR),
        Pin(num=6, name="SCL", func=PIN.INPUT),
        Pin(num=7, name="WP",  func=PIN.INPUT),
        Pin(num=8, name="VCC", func=PIN.PWRIN),
    ],
)


def EEPROM_24C32():
    return _attach_db(_EEPROM_24C32(), "24C32", None)


# Raspberry Pi 40-pin GPIO header (2x20 vertical pin header)
_RPI_HEADER = Part(
    name="RPi_Header", ref_prefix="J", tool=SKIDL, dest=TEMPLATE,
    value="RPi_HEADER",
    footprint="Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    pins=[Pin(num=n, name=f"P{n}", func=PIN.PASSIVE) for n in range(1, 41)],
)


def RPI_HEADER():
    return _attach_db(_RPI_HEADER(), "RPi_Header", None)


# Switchcraft PJRAS2X1S01X dual RCA jack (uses local OPA_PHONO.pretty footprint)
_RCA_DUAL = Part(
    name="PJRAS2X1S01X", ref_prefix="J", tool=SKIDL, dest=TEMPLATE,
    value="RCA_DUAL",
    footprint="OPA_PHONO:PJRAS2X1S01X",
    pins=[
        Pin(num="T1", name="TIP1",    func=PIN.PASSIVE),
        Pin(num="S1", name="SLEEVE1", func=PIN.PASSIVE),
        Pin(num="T2", name="TIP2",    func=PIN.PASSIVE),
        Pin(num="S2", name="SLEEVE2", func=PIN.PASSIVE),
    ],
)


def RCA_DUAL():
    return _attach_db(_RCA_DUAL(), "PJRAS2X1S01X", None)


# =============================================================================
# Helpers
# =============================================================================
def nc(*pins):
    """Mark pins as no-connect to keep ERC quiet."""
    nc_net = Net.fetch("NC")          # singleton no-connect net
    for p in pins:
        p += nc_net


# =============================================================================
# RIAA preamp - one channel
#
# Stage 1 (1/4 OPA1644): non-inverting flat gain
# Stage 2 (1/4 OPA1644): RIAA-shaped gain with 68n shunt in feedback
# Stage 3 (1/2 OPA1612): unity-gain output buffer with AC-couple
# =============================================================================
@subcircuit
def riaa_channel(
    audio_in, audio_out, gnd,
    s1_inp, s1_inn, s1_out,
    s2_inp, s2_inn, s2_out,
    buf_inp, buf_inn, buf_out,
):
    """
    audio_in  : single-ended input from RCA jack
    audio_out : line-level output to ADC anti-alias filter
    s1_*      : pin handles for first OPA1644 section (gain stage)
    s2_*      : pin handles for second OPA1644 section (RIAA stage)
    buf_*     : pin handles for OPA1612 section (output buffer)
    """
    # --- Stage 1: flat gain ---
    r_in   = R(value="47k")
    c_in   = C(value="NP")
    rf1    = R(value="16k")
    rg1    = R(value="499R")
    rg1b   = R(value="16k")

    r_in[1, 2] += audio_in, gnd
    c_in[1, 2] += audio_in, gnd
    audio_in   += s1_inp                # +input

    n_fb1 = Net()
    n_fb1 += s1_inn
    rg1[1, 2]  += n_fb1, gnd
    rg1b[1, 2] += n_fb1, gnd
    rf1[1, 2]  += n_fb1, s1_out

    # --- Inter-stage RIAA passive network ---
    r_riaa  = R(value="2.32k")
    c_riaa1 = C1210(value="68n")
    c_riaa2 = C1206(value="47n")

    n_riaa_mid = Net()
    r_riaa[1, 2]  += s1_out, n_riaa_mid
    c_riaa1[1, 2] += n_riaa_mid, gnd
    c_riaa2[1, 2] += n_riaa_mid, gnd

    # --- Stage 2: RIAA-shaped gain ---
    rf2     = R(value="16k")
    rg2     = R(value="499R")
    rg2b    = R(value="16k")
    c_riaa3 = C1210(value="68n")

    s2_inp += n_riaa_mid
    n_fb2 = Net()
    n_fb2 += s2_inn
    rg2[1, 2]     += n_fb2, gnd
    rg2b[1, 2]    += n_fb2, gnd
    rf2[1, 2]     += n_fb2, s2_out
    c_riaa3[1, 2] += n_fb2, s2_out

    # --- Stage 3: output buffer (OPA1612) ---
    r_pull = R(value="47k")
    r_ser  = R(value="499R")
    c_ac   = C(value="1u")
    r_term = R(value="47k")

    buf_inp += s2_out
    buf_inn += buf_out                 # unity-gain buffer
    r_pull[1, 2] += s2_out, gnd

    n_buf_out = Net()
    r_ser[1, 2] += buf_out, n_buf_out
    c_ac[1, 2]  += n_buf_out, audio_out
    r_term[1, 2] += audio_out, gnd


# =============================================================================
# LTC3265 +-6V charge pump
# Component values per PCB/POWER.kicad_sch.
# =============================================================================
@subcircuit
def ltc3265_psu(vin_5v, vplus_6v, vminus_6v, gnd):
    u3 = LTC3265()

    # Power inputs - both VINP/VINN tied to Pi 5V; ENP/ENN tied high
    u3["VINP"] += vin_5v
    u3["VINN"] += vin_5v
    u3["ENP"]  += vin_5v
    u3["ENN"]  += vin_5v
    u3["GND"]  += gnd
    u3["MODE"] += gnd                  # Burst Mode (lowest noise)

    # RT - default switching frequency: tie to GND
    u3["RT"] += gnd

    # Input bulk
    cin = C0805(value="10u"); cin[1, 2] += vin_5v, gnd

    # Inverting flying cap
    c_inv = C(value="1u")
    c_inv[1, 2] += u3["CINVP"], u3["CINVN"]

    # Boost flying cap
    c_bst = C(value="1u")
    c_bst[1, 2] += u3["CBSTP"], u3["CBSTN"]

    # Bypass caps (BYPP / BYPN reference filtering)
    cbp = C(value="1u"); cbp[1, 2] += u3["BYPP"], gnd
    cbn = C(value="1u"); cbn[1, 2] += u3["BYPN"], gnd

    # LDO output bypass
    cldp = C(value="1u"); cldp[1, 2] += u3["LDOP"], gnd
    cldn = C(value="1u"); cldn[1, 2] += u3["LDON"], gnd

    # +6V feedback divider: 20.5k / 5.1k -> ~+6.13V
    rt_p = R(value="20.5k"); rb_p = R(value="5.1k")
    rt_p[1, 2] += u3["VOUTP"], u3["ADJP"]
    rb_p[1, 2] += u3["ADJP"], gnd
    cop1 = C0805(value="10u"); cop1[1, 2] += u3["VOUTP"], gnd
    cop2 = C0805(value="10u"); cop2[1, 2] += u3["VOUTP"], gnd
    u3["VOUTP"] += vplus_6v

    # -6V feedback divider
    rt_n = R(value="20.5k"); rb_n = R(value="5.1k")
    rt_n[1, 2] += u3["VOUTN"], u3["ADJN"]
    rb_n[1, 2] += u3["ADJN"], gnd
    con1 = C0805(value="10u"); con1[1, 2] += u3["VOUTN"], gnd
    con2 = C0805(value="10u"); con2[1, 2] += u3["VOUTN"], gnd
    u3["VOUTN"] += vminus_6v


# =============================================================================
# PCM1863 ADC + single-ended anti-alias front end
# =============================================================================
@subcircuit
def adc_input_filter(line_in, adc_pin_pos, adc_pin_neg, gnd):
    """AC-couple + RC anti-alias driving a PCM1863 differential input."""
    c_ac   = C0805(value="2.2u")
    r_ser  = R(value="3.3k")
    r_bias = R(value="22k")
    c_aa   = C(value="470p")

    n_after_c = Net()
    c_ac[1, 2]  += line_in, n_after_c
    r_ser[1, 2] += n_after_c, adc_pin_pos
    c_aa[1, 2]  += adc_pin_pos, gnd

    # Negative leg of the differential input is biased to AGND through 22k
    r_bias[1, 2] += adc_pin_neg, gnd


@subcircuit
def pcm1863_block(
    line_l, line_r,
    avdd_3v3, dvdd_3v3, gnd,
    i2s_bck, i2s_lrck, i2s_dout,
    i2c_sda, i2c_scl,
):
    u_adc = PCM1863()

    # Power
    u_adc["AVDD"] += avdd_3v3
    u_adc["DVDD"] += dvdd_3v3
    u_adc["AGND"] += gnd
    u_adc["DGND"] += gnd

    # Decoupling
    cavdd = C(value="1u"); cavdd[1, 2] += avdd_3v3, gnd
    cdvdd = C(value="1u"); cdvdd[1, 2] += dvdd_3v3, gnd
    cref  = C0805(value="10u"); cref[1, 2] += u_adc["REF_FILT"], gnd

    # Audio inputs
    adc_input_filter(line_l, u_adc["VINL1+"], u_adc["VINL1-"], gnd)
    adc_input_filter(line_r, u_adc["VINR1+"], u_adc["VINR1-"], gnd)
    nc(u_adc["VINL2"], u_adc["VINR2"])

    # I2S to Pi (PCM1863 master)
    u_adc["BCK"]  += i2s_bck
    u_adc["LRCK"] += i2s_lrck
    u_adc["DOUT"] += i2s_dout

    # I2C control
    u_adc["SDA"] += i2c_sda
    u_adc["SCL"] += i2c_scl

    # Local I2C pull-ups (Pi has its own; harmless to repeat).
    rsda = R(value="4.7k"); rsda[1, 2] += i2c_sda, dvdd_3v3
    rscl = R(value="4.7k"); rscl[1, 2] += i2c_scl, dvdd_3v3

    # Mode select & system clock - tie to known levels
    u_adc["MD"]  += gnd                 # device address LSB low -> 0x4A
    u_adc["MS"]  += gnd                 # I2C software-control mode
    u_adc["SCK"] += gnd                 # PLL generates clocks internally
    nc(u_adc["GPIO3"])


# =============================================================================
# 24C32 HAT-ID EEPROM
# =============================================================================
@subcircuit
def hat_eeprom(id_sd, id_sc, vcc_3v3, gnd):
    u_ee = EEPROM_24C32()

    u_ee["VCC"] += vcc_3v3
    u_ee["VSS"] += gnd
    u_ee["A0"]  += gnd
    u_ee["A1"]  += gnd
    u_ee["A2"]  += gnd
    u_ee["WP"]  += gnd                  # WP=GND lets the Pi bootloader write
    u_ee["SDA"] += id_sd
    u_ee["SCL"] += id_sc

    cbp = C(value="100n"); cbp[1, 2] += vcc_3v3, gnd

    # HAT spec requires 3.9k pull-ups on the ID bus.
    rsd = R(value="3.9k"); rsd[1, 2] += id_sd, vcc_3v3
    rsc = R(value="3.9k"); rsc[1, 2] += id_sc, vcc_3v3


# =============================================================================
# Top-level assembly
# =============================================================================
def build():
    # ---- Power nets ----
    pi_5v   = Net("PI_5V");  pi_5v.drive  = POWER
    pi_3v3  = Net("PI_3V3"); pi_3v3.drive = POWER
    vplus   = Net("+6V");    vplus.drive  = POWER
    vminus  = Net("-6V");    vminus.drive = POWER
    gnd     = Net("GND");    gnd.drive    = POWER

    # ---- Audio nets ----
    in_l, in_r   = Net("IN_L"), Net("IN_R")
    out_l, out_r = Net("OUT_L"), Net("OUT_R")

    # ---- I2S / I2C / ID-bus nets ----
    i2s_bck  = Net("I2S_BCK")
    i2s_lrck = Net("I2S_LRCK")
    i2s_dout = Net("I2S_DOUT")
    i2c_sda  = Net("I2C_SDA")
    i2c_scl  = Net("I2C_SCL")
    id_sd    = Net("ID_SD")
    id_sc    = Net("ID_SC")

    # ---- Op-amps (one quad + one dual, shared between channels) ----
    u1 = OPA1644()
    u2 = OPA1612()

    # Op-amp supply pins
    u1["V+"] += vplus;  u1["V-"] += vminus
    u2["V+"] += vplus;  u2["V-"] += vminus

    # Decoupling on each op-amp supply pin
    for p in (u1["V+"], u2["V+"]):
        c = C(value="100n"); c[1, 2] += vplus, gnd
    for p in (u1["V-"], u2["V-"]):
        c = C(value="100n"); c[1, 2] += vminus, gnd

    # Left channel: OPA1644 sections A and B + OPA1612 section A
    riaa_channel(
        in_l, out_l, gnd,
        s1_inp=u1["+INA"], s1_inn=u1["-INA"], s1_out=u1["OUTA"],
        s2_inp=u1["+INB"], s2_inn=u1["-INB"], s2_out=u1["OUTB"],
        buf_inp=u2["+INA"], buf_inn=u2["-INA"], buf_out=u2["OUTA"],
    )
    # Right channel: OPA1644 sections C and D + OPA1612 section B
    riaa_channel(
        in_r, out_r, gnd,
        s1_inp=u1["+INC"], s1_inn=u1["-INC"], s1_out=u1["OUTC"],
        s2_inp=u1["+IND"], s2_inn=u1["-IND"], s2_out=u1["OUTD"],
        buf_inp=u2["+INB"], buf_inn=u2["-INB"], buf_out=u2["OUTB"],
    )

    # ---- Power supply: Pi 5V -> +-6V analog ----
    ltc3265_psu(pi_5v, vplus, vminus, gnd)

    # ---- ADC ----
    pcm1863_block(
        out_l, out_r,
        avdd_3v3=pi_3v3, dvdd_3v3=pi_3v3, gnd=gnd,
        i2s_bck=i2s_bck, i2s_lrck=i2s_lrck, i2s_dout=i2s_dout,
        i2c_sda=i2c_sda, i2c_scl=i2c_scl,
    )

    # ---- HAT-ID EEPROM ----
    hat_eeprom(id_sd, id_sc, pi_3v3, gnd)

    # ---- RCA jack (stereo input) ----
    j_rca = RCA_DUAL()
    j_rca["TIP1"]    += in_l
    j_rca["SLEEVE1"] += gnd
    j_rca["TIP2"]    += in_r
    j_rca["SLEEVE2"] += gnd

    # ---- Raspberry Pi 40-pin GPIO header ----
    # Pin map (B+/2/3/4/5):
    #   1  3V3      2  5V        3  BCM2 SDA   4  5V
    #   5  BCM3 SCL 6  GND       7  BCM4       8  BCM14
    #   9  GND     10  BCM15    11  BCM17     12  BCM18 <- I2S BCK
    #  13  BCM27   14  GND      15  BCM22     16  BCM23
    #  17  3V3     18  BCM24    19  BCM10     20  GND
    #  21  BCM9    22  BCM25    23  BCM11     24  BCM8
    #  25  GND     26  BCM7     27  ID_SD     28  ID_SC
    #  29  BCM5    30  GND      31  BCM6      32  BCM12
    #  33  BCM13   34  GND      35  BCM19 LRCK 36 BCM16
    #  37  BCM26   38  BCM20 <- I2S DIN       39  GND   40 BCM21
    j = RPI_HEADER()

    j[1]  += pi_3v3
    j[17] += pi_3v3
    j[2]  += pi_5v
    j[4]  += pi_5v
    for p in (6, 9, 14, 20, 25, 30, 34, 39):
        j[p] += gnd

    j[3]  += i2c_sda    # BCM2
    j[5]  += i2c_scl    # BCM3
    j[12] += i2s_bck    # BCM18
    j[35] += i2s_lrck   # BCM19
    j[38] += i2s_dout   # BCM20
    j[27] += id_sd      # BCM0
    j[28] += id_sc      # BCM1

    nc(*[j[n] for n in (
        7, 8, 10, 11, 13, 15, 16, 18, 19, 21, 22, 23, 24,
        26, 29, 31, 32, 33, 36, 37, 40,
    )])


if __name__ == "__main__":
    import sys
    build()
    ERC()
    if "--erc" not in sys.argv:
        generate_netlist(file_="opa_phono_pi.net")
